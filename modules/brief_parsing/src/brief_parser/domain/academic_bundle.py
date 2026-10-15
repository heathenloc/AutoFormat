"""Academic parse-only Bundle without a generic ExecutionBrief."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import SerializerFunctionWrapHandler, model_serializer, model_validator

from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.academic_source_review import AcademicSourceReview
from brief_parser.domain.base import StrictModel
from brief_parser.domain.bundle import ParseDiagnostics, ParseRenderings
from brief_parser.domain.pipeline import ParseManifest
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.domain.template_layout import TemplateLayoutReport


class AcademicParseBundle(StrictModel):
    bundle_version: Literal[
        "academic-parse-bundle/1.0", "academic-parse-bundle/1.1",
        "academic-parse-bundle/1.2",
        "academic-parse-bundle/1.3",
        "academic-parse-bundle/1.4",
        "academic-parse-bundle/1.5",
        "academic-parse-bundle/1.6",
    ] = "academic-parse-bundle/1.2"
    manifest: ParseManifest
    requirement_ir: RequirementIR
    renderings: ParseRenderings
    diagnostics: ParseDiagnostics
    format_ruleset: AcademicFormatRuleSet | None = None
    source_review: AcademicSourceReview | None = None
    template_layout: TemplateLayoutReport | None = None

    @model_serializer(mode="wrap")
    def preserve_historical_shape(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.bundle_version not in {"academic-parse-bundle/1.3", "academic-parse-bundle/1.4", "academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}:
            data.pop("source_review", None)
        if self.bundle_version not in {"academic-parse-bundle/1.4", "academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}:
            data.pop("template_layout", None)
        return data

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        expected_ruleset_version = {
            "academic-parse-bundle/1.0": None,
            "academic-parse-bundle/1.1": "academic-format-rule-set/1.1",
            "academic-parse-bundle/1.2": "academic-format-rule-set/1.2",
            "academic-parse-bundle/1.3": "academic-format-rule-set/1.3",
            "academic-parse-bundle/1.4": "academic-format-rule-set/1.3",
            "academic-parse-bundle/1.5": "academic-format-rule-set/1.4",
            "academic-parse-bundle/1.6": "academic-format-rule-set/1.5",
        }[self.bundle_version]
        if ((self.format_ruleset.schema_version if self.format_ruleset else None)
                != expected_ruleset_version):
            raise ValueError("academic bundle version and format ruleset differ")
        if (self.source_review is not None) != (self.bundle_version in {"academic-parse-bundle/1.3", "academic-parse-bundle/1.4", "academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}):
            raise ValueError("source review requires academic bundle 1.3 or 1.4")
        if (self.template_layout is not None) != (self.bundle_version in {"academic-parse-bundle/1.4", "academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}):
            raise ValueError("template layout requires academic bundle 1.4")
        current = self.bundle_version in {"academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}
        review_version = "academic-source-review/1.2" if self.bundle_version.endswith("1.6") else "academic-source-review/1.1" if current else "academic-source-review/1.0"
        if self.source_review and self.source_review.schema_version != review_version:
            raise ValueError("source review version differs from academic bundle")
        if self.template_layout and self.template_layout.schema_version != ("academic-template-layout/1.1" if current else "academic-template-layout/1.0"):
            raise ValueError("template layout version differs from academic bundle")
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
            for review in ruleset.candidate_reviews:
                if review.source_requirement_id not in {item.id for item in self.requirement_ir.requirements} or not set(review.evidence_ids) <= set(evidence_index):
                    raise ValueError("candidate review differs from source IR")
            # A stored handoff must be reproducible from the exact IR evidence;
            # validating only the quote hash would allow a changed format value.
            if self.bundle_version == "academic-parse-bundle/1.1":
                from brief_parser.compilers.academic_common_v1_1 import (
                    AcademicCommonFormatExtractor,
                )
            elif self.bundle_version == "academic-parse-bundle/1.2":
                from brief_parser.compilers.academic_common_v1_2 import AcademicCommonFormatExtractor
            elif self.bundle_version in {"academic-parse-bundle/1.3", "academic-parse-bundle/1.4"}:
                from brief_parser.compilers.academic_common_v1_3 import AcademicCommonFormatExtractor
            elif self.bundle_version == "academic-parse-bundle/1.5":
                from brief_parser.compilers.academic_semantic_extractor_v1_4 import AcademicCommonFormatExtractor
            else:
                from brief_parser.compilers.academic_common import AcademicCommonFormatExtractor

            if ruleset != AcademicCommonFormatExtractor().extract(self.requirement_ir):
                raise ValueError("academic format ruleset differs from source evidence")
            if self.source_review is not None:
                if self.bundle_version == "academic-parse-bundle/1.6":
                    from brief_parser.compilers.academic_source_review import build_source_review
                elif self.bundle_version == "academic-parse-bundle/1.5":
                    from brief_parser.compilers.academic_source_review_v1_1 import build_source_review
                else:
                    from brief_parser.compilers.academic_source_review_v1_0 import build_source_review
                if self.source_review != build_source_review(self.requirement_ir, ruleset):
                    raise ValueError("academic source review differs from source evidence")
            if self.template_layout is not None:
                if current:
                    from brief_parser.compilers.template_layout import build_template_groups
                else:
                    from brief_parser.compilers.template_layout_v1_0 import build_template_groups
                layout = self.template_layout
                if (layout.source_artifact_id != self.requirement_ir.artifact_id
                        or layout.source_artifact_version != self.requirement_ir.artifact_version
                        or [(p.source_id, p.sha256, p.kind) for p in layout.source_profiles]
                        != [(p.source_id, p.sha256, p.kind) for p in self.requirement_ir.source_manifest]):
                    raise ValueError("template layout differs from source manifest")
                if layout.groups != build_template_groups(layout.observations, ruleset):
                    raise ValueError("template groups differ from observations and explicit rules")
        return self
