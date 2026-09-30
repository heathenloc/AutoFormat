"""Stable transport-neutral Parse Bundle and diagnostics contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.execution_brief import ExecutionBrief
from brief_parser.domain.pipeline import ParseManifest, ProviderCallRecord, StageRecord
from brief_parser.domain.requirement_ir import RequirementIR


class ParseRenderings(StrictModel):
    markdown: Annotated[str, Field(min_length=1)]


class ParseDiagnostics(StrictModel):
    schema_version: Literal["parse-diagnostics/1.0"] = "parse-diagnostics/1.0"
    warning_codes: list[str] = Field(default_factory=list)
    readiness_reason_codes: list[str] = Field(default_factory=list)
    conflict_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    stages: list[StageRecord] = Field(default_factory=list)
    provider_calls: list[ProviderCallRecord] = Field(default_factory=list)


class ParseBundle(StrictModel):
    """Host-neutral result consumed by CLI, standalone API, or future integrations."""

    bundle_version: Literal["parse-bundle/1.0"] = "parse-bundle/1.0"
    manifest: ParseManifest
    requirement_ir: RequirementIR
    execution_briefs: dict[Identifier, ExecutionBrief]
    renderings: ParseRenderings
    diagnostics: ParseDiagnostics

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if self.manifest.artifact_id != self.requirement_ir.artifact_id:
            raise ValueError("bundle manifest and Requirement IR artifact ids differ")
        if self.manifest.artifact_version != self.requirement_ir.artifact_version:
            raise ValueError("bundle manifest and Requirement IR versions differ")
        if set(self.execution_briefs) != set(self.manifest.requested_task_types):
            raise ValueError("bundle execution briefs do not match requested task types")
        for task_type, brief in self.execution_briefs.items():
            if task_type != brief.task_type:
                raise ValueError("bundle execution brief key does not match task type")
            if brief.source_artifact_id != self.requirement_ir.artifact_id:
                raise ValueError("bundle execution brief references another artifact")
            if brief.source_artifact_version != self.requirement_ir.artifact_version:
                raise ValueError("bundle execution brief references another version")
        if (
            self.diagnostics.readiness_reason_codes
            != self.requirement_ir.quality.readiness_reason_codes
        ):
            raise ValueError("bundle diagnostics readiness reasons differ from the IR")
        return self
