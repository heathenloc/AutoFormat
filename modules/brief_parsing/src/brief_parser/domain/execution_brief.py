"""Task-specific Execution Brief v1 contract."""

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from brief_parser.domain.base import Identifier, Locale, StrictModel
from brief_parser.domain.enums import DownstreamPolicy, ExecutionReadiness, Priority


class ExecutionItem(StrictModel):
    id: Identifier
    label: Annotated[str, Field(min_length=1)]
    value: JsonValue
    evidence_refs: list[Identifier] = Field(default_factory=list)
    source_requirement_id: Identifier | None = None


class ExecutionConstraint(ExecutionItem):
    priority: Priority
    condition: str | None = None
    downstream_policy: DownstreamPolicy


class AppliedDefault(StrictModel):
    id: Identifier
    label: Annotated[str, Field(min_length=1)]
    value: JsonValue
    source: Annotated[str, Field(min_length=1)]


class ExecutionUnresolved(StrictModel):
    id: Identifier
    topic: Identifier
    description: Annotated[str, Field(min_length=1)]
    evidence_refs: list[Identifier] = Field(default_factory=list)
    downstream_policy: Literal["do_not_assume", "block"]


class ConsumerPolicy(StrictModel):
    must_enforce_blockers: bool = True
    must_not_infer_unresolved: bool = True


class ExecutionBrief(StrictModel):
    schema_version: Literal["execution-brief/1.0"] = "execution-brief/1.0"
    task_type: Identifier
    source_artifact_id: Identifier
    source_artifact_version: Annotated[int, Field(gt=0)]
    readiness: ExecutionReadiness
    locale: Locale = "zh-CN"
    objective: list[ExecutionItem] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)
    deliverables: list[ExecutionConstraint] = Field(default_factory=list)
    hard_constraints: list[ExecutionConstraint] = Field(default_factory=list)
    prohibitions: list[ExecutionConstraint] = Field(default_factory=list)
    preferences: list[ExecutionConstraint] = Field(default_factory=list)
    references: list[ExecutionItem] = Field(default_factory=list)
    additional_constraints: list[ExecutionConstraint] = Field(default_factory=list)
    unresolved: list[ExecutionUnresolved] = Field(default_factory=list)
    applied_defaults: list[AppliedDefault] = Field(default_factory=list)
    consumer_policy: ConsumerPolicy = Field(default_factory=ConsumerPolicy)
