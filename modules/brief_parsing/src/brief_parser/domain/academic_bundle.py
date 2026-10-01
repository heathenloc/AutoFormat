"""Academic parse-only Bundle without a generic ExecutionBrief."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.base import StrictModel
from brief_parser.domain.bundle import ParseDiagnostics, ParseRenderings
from brief_parser.domain.pipeline import ParseManifest
from brief_parser.domain.requirement_ir import RequirementIR


class AcademicParseBundle(StrictModel):
    bundle_version: Literal[
        "academic-parse-bundle/1.0", "academic-parse-bundle/1.1"
    ] = "academic-parse-bundle/1.1"
    manifest: ParseManifest
    requirement_ir: RequirementIR
    renderings: ParseRenderings
    diagnostics: ParseDiagnostics
    format_ruleset: AcademicFormatRuleSet | None = None

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if ((self.bundle_version == "academic-parse-bundle/1.1")
                != (self.format_ruleset is not None)):
            raise ValueError("academic bundle version and format ruleset differ")
        if self.manifest.requested_task_types != ["format_academic_paper"]:
            raise ValueError("academic parse bundle requires the academic task marker")
        if (self.manifest.domain_pack.id != "academic_paper"
                or self.requirement_ir.domain_pack != self.manifest.domain_pack):
            raise ValueError("academic parse bundle requires matching academic domain")
        if (self.manifest.artifact_id != self.requirement_ir.artifact_id
                or self.manifest.artifact_version != self.requirement_ir.artifact_version
                or self.manifest.request_id != self.requirement_ir.request_id):
            raise ValueError("academic parse bundle manifest and IR differ")
        manifest_sources = [
            (item.source_id, item.sha256, item.parser_id, item.parser_version,
             item.extraction_status)
            for item in self.manifest.sources
        ]
        ir_sources = [
            (item.source_id, item.sha256, item.parser_id, item.parser_version,
             item.extraction_status)
            for item in self.requirement_ir.source_manifest
        ]
        if manifest_sources != ir_sources:
            raise ValueError("academic parse bundle sources differ from IR")
        if (self.diagnostics.readiness_reason_codes
                != self.requirement_ir.quality.readiness_reason_codes
                or self.diagnostics.conflict_count
                != self.requirement_ir.quality.conflict_count
                or self.diagnostics.unresolved_count
                != self.requirement_ir.quality.unresolved_count
                or self.diagnostics.coverage_ratio
                != self.requirement_ir.quality.coverage_ratio):
            raise ValueError("academic parse bundle diagnostics differ from IR")
        if self.format_ruleset is not None:
            ruleset = self.format_ruleset
            if (ruleset.source_artifact_id != self.requirement_ir.artifact_id
                    or ruleset.source_artifact_version != self.requirement_ir.artifact_version
                    or ruleset.domain_pack != self.requirement_ir.domain_pack):
                raise ValueError("academic format ruleset points to another IR")
            evidence_index = self.requirement_ir.evidence_index
            for rule in ruleset.rules:
                if any(evidence_index.get(ref.evidence_id) != ref
                       for ref in rule.evidence_refs):
                    raise ValueError("academic format rule evidence differs from IR")
            for issue in ruleset.issues:
                if not set(issue.evidence_ids) <= set(evidence_index):
                    raise ValueError("academic format issue evidence differs from IR")
            # A stored handoff must be reproducible from the exact IR evidence;
            # validating only the quote hash would allow a changed format value.
            from brief_parser.compilers.academic_common import AcademicCommonFormatExtractor

            if ruleset != AcademicCommonFormatExtractor().extract(self.requirement_ir):
                raise ValueError("academic format ruleset differs from source evidence")
        return self
