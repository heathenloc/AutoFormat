"""Compile one Requirement IR into task briefs and a human-readable result."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field, model_validator

from brief_parser.compilers.context import ContextCompiler
from brief_parser.compilers.domain_validation import project_domain_issues
from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.execution_brief import (
    ExecutionBrief,
    ExecutionItem,
    ExecutionUnresolved,
)
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.renderers.markdown import MarkdownResultRenderer


class CompiledParseOutputs(StrictModel):
    requirement_ir: RequirementIR
    execution_briefs: dict[Identifier, ExecutionBrief]
    result_markdown: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_task_keys(self) -> CompiledParseOutputs:
        evidence_ids = set(self.requirement_ir.evidence_index)
        requirement_ids = {item.id for item in self.requirement_ir.requirements}
        for task_type, brief in self.execution_briefs.items():
            if task_type != brief.task_type:
                raise ValueError("execution brief key must equal task_type")
            if brief.source_artifact_id != self.requirement_ir.artifact_id:
                raise ValueError("execution brief source artifact does not match IR")
            if brief.source_artifact_version != self.requirement_ir.artifact_version:
                raise ValueError("execution brief source version does not match IR")
            evidence_backed: list[ExecutionItem | ExecutionUnresolved] = [
                *brief.objective,
                *brief.deliverables,
                *brief.hard_constraints,
                *brief.prohibitions,
                *brief.preferences,
                *brief.references,
                *brief.additional_constraints,
                *brief.unresolved,
            ]
            for item in evidence_backed:
                if not set(item.evidence_refs) <= evidence_ids:
                    raise ValueError("execution brief references unknown evidence")
            constraints = [
                *brief.deliverables,
                *brief.hard_constraints,
                *brief.prohibitions,
                *brief.preferences,
                *brief.additional_constraints,
            ]
            if any(
                item.source_requirement_id not in requirement_ids for item in constraints
            ):
                raise ValueError("execution brief references unknown requirement")
        return self


class OutputCompiler:
    def __init__(
        self,
        *,
        context_compiler: ContextCompiler | None = None,
        renderer: MarkdownResultRenderer | None = None,
    ) -> None:
        self._context_compiler = context_compiler or ContextCompiler()
        self._renderer = renderer or MarkdownResultRenderer()

    @property
    def context_compiler(self) -> ContextCompiler:
        return self._context_compiler

    def compile(
        self,
        requirement_ir: RequirementIR,
        domain_pack: DomainPack,
        *,
        task_types: Sequence[str],
    ) -> CompiledParseOutputs:
        if not task_types:
            raise ValueError("at least one task type is required")
        if len(task_types) != len(set(task_types)):
            raise ValueError("task types must be unique")
        domain_issues = self._context_compiler.validate_domain(
            requirement_ir,
            domain_pack,
        )
        projected_ir = project_domain_issues(requirement_ir, domain_issues)
        execution_briefs = {
            task_type: self._context_compiler.compile(
                projected_ir,
                domain_pack,
                task_type=task_type,
                domain_issues=domain_issues,
            )
            for task_type in task_types
        }
        markdown = self._renderer.render(projected_ir, execution_briefs)
        return CompiledParseOutputs(
            requirement_ir=projected_ir,
            execution_briefs=execution_briefs,
            result_markdown=markdown,
        )

    def compile_parse_only(
        self,
        requirement_ir: RequirementIR,
        domain_pack: DomainPack,
    ) -> CompiledParseOutputs:
        """Project validated facts and diagnostics without a generic task brief."""
        if (domain_pack.id != "academic_paper"
                or requirement_ir.domain_pack.id != domain_pack.id
                or requirement_ir.domain_pack.version != domain_pack.version):
            raise ValueError("Academic parse-only requires the matching domain pack.")
        issues = self._context_compiler.validate_domain(requirement_ir, domain_pack)
        projected_ir = project_domain_issues(requirement_ir, issues)
        return CompiledParseOutputs(
            requirement_ir=projected_ir,
            execution_briefs={},
            result_markdown=self._renderer.render(projected_ir, {}),
        )
