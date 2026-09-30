"""Assemble the stable Parse Bundle from pipeline and compiler outputs."""

from __future__ import annotations

from brief_parser.application.output_compilation import CompiledParseOutputs
from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics, ParseRenderings
from brief_parser.domain.pipeline import PipelineResult


def build_parse_bundle(
    pipeline_result: PipelineResult,
    outputs: CompiledParseOutputs,
) -> ParseBundle:
    ir = outputs.requirement_ir
    warning_codes = {warning for source in ir.source_manifest for warning in source.warnings}
    warning_codes.update(
        conflict.reason_code for conflict in ir.conflicts if conflict.severity.value != "blocker"
    )
    warning_codes.update(item.reason_code for item in ir.unresolved_items)
    warning_codes.update(item.reason_code for item in ir.unclassified_content)
    return ParseBundle(
        manifest=pipeline_result.manifest.model_copy(
            update={"readiness_reason_codes": ir.quality.readiness_reason_codes}
        ),
        requirement_ir=ir,
        execution_briefs=outputs.execution_briefs,
        renderings=ParseRenderings(markdown=outputs.result_markdown),
        diagnostics=ParseDiagnostics(
            warning_codes=sorted(warning_codes),
            readiness_reason_codes=ir.quality.readiness_reason_codes,
            conflict_count=ir.quality.conflict_count,
            unresolved_count=ir.quality.unresolved_count,
            coverage_ratio=ir.quality.coverage_ratio,
            stages=pipeline_result.manifest.stages,
            provider_calls=pipeline_result.manifest.provider_calls,
        ),
    )
