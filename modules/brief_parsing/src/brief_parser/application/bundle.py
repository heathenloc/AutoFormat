"""Assemble the stable Parse Bundle from pipeline and compiler outputs."""

from __future__ import annotations

from brief_parser.application.output_compilation import CompiledParseOutputs
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics, ParseRenderings
from brief_parser.domain.pipeline import PipelineResult
from brief_parser.domain.requirement_ir import RequirementIR


def build_parse_bundle(
    pipeline_result: PipelineResult,
    outputs: CompiledParseOutputs,
) -> ParseBundle:
    ir = outputs.requirement_ir
    return ParseBundle(
        manifest=pipeline_result.manifest.model_copy(
            update={"readiness_reason_codes": ir.quality.readiness_reason_codes}
        ),
        requirement_ir=ir,
        execution_briefs=outputs.execution_briefs,
        renderings=ParseRenderings(markdown=outputs.result_markdown),
        diagnostics=_diagnostics(ir, pipeline_result),
    )


def _diagnostics(ir: RequirementIR, pipeline_result: PipelineResult) -> ParseDiagnostics:
    warning_codes = {warning for source in ir.source_manifest for warning in source.warnings}
    warning_codes.update(
        conflict.reason_code for conflict in ir.conflicts if conflict.severity.value != "blocker"
    )
    warning_codes.update(item.reason_code for item in ir.unresolved_items)
    warning_codes.update(item.reason_code for item in ir.unclassified_content)
    return ParseDiagnostics(
        warning_codes=sorted(warning_codes),
        readiness_reason_codes=ir.quality.readiness_reason_codes,
        conflict_count=ir.quality.conflict_count,
        unresolved_count=ir.quality.unresolved_count,
        coverage_ratio=ir.quality.coverage_ratio,
        stages=pipeline_result.manifest.stages,
        provider_calls=pipeline_result.manifest.provider_calls,
    )


def build_academic_parse_bundle(
    pipeline_result: PipelineResult,
    outputs: CompiledParseOutputs,
    *,
    format_ruleset: AcademicFormatRuleSet | None = None,
) -> AcademicParseBundle:
    """Reuse validated diagnostics while omitting task-specific ExecutionBriefs."""
    if outputs.execution_briefs:
        raise ValueError("Academic parse-only output cannot contain ExecutionBriefs.")
    ir = outputs.requirement_ir
    return AcademicParseBundle(
        bundle_version=("academic-parse-bundle/1.2" if format_ruleset is not None
                        else "academic-parse-bundle/1.0"),
        manifest=pipeline_result.manifest.model_copy(update={
            "readiness_reason_codes": ir.quality.readiness_reason_codes,
        }),
        requirement_ir=ir,
        renderings=ParseRenderings(markdown=outputs.result_markdown),
        diagnostics=_diagnostics(ir, pipeline_result),
        format_ruleset=format_ruleset,
    )
