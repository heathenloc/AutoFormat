"""Assemble the stable Parse Bundle from pipeline and compiler outputs."""

from __future__ import annotations

from brief_parser.application.output_compilation import CompiledParseOutputs
from brief_parser.compilers.academic_source_review import build_source_review, render_source_review
from brief_parser.compilers.template_layout import render_template_report
from brief_parser.compilers.academic_scope import render_rule_semantics
from brief_parser.compilers.academic_candidates import render_candidate_review
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics, ParseRenderings
from brief_parser.domain.pipeline import PipelineResult
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.domain.template_layout import TemplateLayoutReport


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
    template_layout: TemplateLayoutReport | None = None,
) -> AcademicParseBundle:
    """Reuse validated diagnostics while omitting task-specific ExecutionBriefs."""
    if outputs.execution_briefs:
        raise ValueError("Academic parse-only output cannot contain ExecutionBriefs.")
    if format_ruleset is not None and template_layout is None:
        raise ValueError("Current academic handoff requires a template report, including for non-DOCX sources.")
    ir = outputs.requirement_ir
    review = build_source_review(ir, format_ruleset) if format_ruleset is not None else None
    return AcademicParseBundle(
        bundle_version=("academic-parse-bundle/1.6" if format_ruleset is not None else "academic-parse-bundle/1.0"),
        manifest=pipeline_result.manifest.model_copy(update={
            "readiness_reason_codes": ir.quality.readiness_reason_codes,
        }),
        requirement_ir=ir,
        renderings=ParseRenderings(markdown=outputs.result_markdown + (
            "\n" + render_source_review(review, ir) if review is not None else ""
        ) + ("\n" + render_template_report(template_layout) if template_layout is not None else "")
          + ("\n" + render_rule_semantics(format_ruleset) if format_ruleset and format_ruleset.schema_version in {"academic-format-rule-set/1.4", "academic-format-rule-set/1.5"} else "")
          + ("\n" + render_candidate_review(format_ruleset) if format_ruleset and format_ruleset.schema_version == "academic-format-rule-set/1.5" else "")),
        diagnostics=_diagnostics(ir, pipeline_result),
        format_ruleset=format_ruleset,
        source_review=review,
        template_layout=template_layout,
    )
