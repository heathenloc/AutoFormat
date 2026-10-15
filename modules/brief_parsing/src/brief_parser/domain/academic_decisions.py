"""Versioned user answers and immutable resolved formatting snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, JsonValue, model_validator

from brief_parser.domain.base import StrictModel, Identifier, Sha256Hex
from brief_parser.domain.academic_format import AcademicTarget, AcademicValue, AcademicFormatIssue
from brief_parser.domain.academic_semantics import (
    AcademicRuleSemantics, AcademicRuleScope, AcademicRuleRelation, AcademicRuleConflict, AcademicRuleFragment, AcademicCondition,
)
from brief_parser.domain.requirement_ir import EvidenceReference, DomainPackRef
from brief_parser.domain.template_layout import TemplateObservation

TaskId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class SubmissionContext(StrictModel):
    medium: Literal["print", "electronic"]
    channel: Literal["other", "system_upload"] | None = None

    @model_validator(mode="after")
    def validate_channel(self) -> Self:
        if self.medium == "print" and self.channel is not None:
            raise ValueError("print submission has no electronic channel")
        if self.medium == "electronic" and self.channel is None:
            raise ValueError("electronic submission needs an explicit channel")
        return self


class FormatClarification(StrictModel):
    property_id: Identifier
    normalized: JsonValue
    unit: str | None = None
    semantic_role: Identifier | None = None
    scope: AcademicRuleScope | None = None


class AcademicAnswer(StrictModel):
    action: Literal["set_submission", "confirm_condition", "select_rule", "keep_brief", "select_template",
                    "accept_template", "reject_template", "clarify_format", "skip", "defer", "ignore"]
    submission: SubmissionContext | None = None
    applies: StrictBool | None = None
    selected_id: Identifier | None = None
    format: FormatClarification | None = None
    scope: AcademicRuleScope | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        fields = {name for name in ("submission", "applies", "selected_id", "format", "scope") if getattr(self, name) is not None}
        required = {"set_submission": {"submission"}, "confirm_condition": {"applies"},
                    "select_rule": {"selected_id"}, "select_template": {"selected_id"},
                    "clarify_format": {"format"}}.get(self.action, set())
        if self.action == "confirm_condition" and self.applies is True and self.scope is not None:
            required = required | {"scope"}
        if fields != required:
            raise ValueError("answer fields differ from its action")
        return self


class AcademicDecisionRequest(StrictModel):
    schema_version: Literal["academic-decision-request/1.0"] = "academic-decision-request/1.0"
    request_id: TaskId
    base_version_id: TaskId
    expected_snapshot_id: Sha256Hex
    question_id: Identifier
    answer: AcademicAnswer
    raw_answer: Annotated[str, Field(max_length=2048)] = ""
    supersedes_decision_id: TaskId | None = None


class AcademicQuestion(StrictModel):
    question_id: Identifier
    kind: Literal["submission", "condition", "conflict", "source_mismatch", "template_inconsistent",
                  "template_category", "value", "clarification", "source_review"]
    phase: Literal["resolve_requirements", "confirm_template"]
    status: Literal["pending", "blocked", "answered", "skipped", "deferred"] = "pending"
    prompt: str
    allowed_actions: list[str]
    rule_ids: list[Identifier] = Field(default_factory=list)
    group_ids: list[Identifier] = Field(default_factory=list)
    issue_ids: list[Identifier] = Field(default_factory=list)
    review_ids: list[Identifier] = Field(default_factory=list)
    property_id: Identifier | None = None
    semantic_role: Identifier | None = None
    scope: AcademicRuleScope | None = None
    character_scope: Identifier = "all"
    condition: AcademicCondition | None = None
    requires_scope: bool = False
    category: Identifier | None = None
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    observations: list[TemplateObservation] = Field(default_factory=list)
    candidate_values: list[AcademicValue] = Field(default_factory=list)
    reason: str


class AcademicDecisionEvent(StrictModel):
    schema_version: Literal["academic-rule-decision/1.0"] = "academic-rule-decision/1.0"
    decision_id: TaskId
    task_id: TaskId
    source_bundle_sha256: Sha256Hex
    created_at: str
    request: AcademicDecisionRequest
    question_kind: str

    @model_validator(mode="after")
    def validate_question(self) -> Self:
        from datetime import datetime
        if datetime.fromisoformat(self.created_at).tzinfo is None:
            raise ValueError("decision timestamp must include a timezone")
        return self


class AcademicQuestionQueue(StrictModel):
    schema_version: Literal["academic-question-queue/1.0"] = "academic-question-queue/1.0"
    task_id: TaskId
    base_version_id: TaskId
    snapshot_id: Sha256Hex
    revision: Annotated[int, Field(ge=0, le=256)]
    reopen_decision_id: TaskId | None = None
    questions: list[AcademicQuestion]


class AcademicDecisionEffect(StrictModel):
    decision_id: TaskId
    status: Literal["applied", "superseded", "invalidated"]
    reason: str


class AcademicEffectiveRule(StrictModel):
    schema_version: Literal["academic-effective-rule/1.0"] = "academic-effective-rule/1.0"
    rule_id: Identifier
    source_kind: Literal["brief_explicit", "template_observation_confirmed", "user_decision"]
    source_rule_ids: list[Identifier]
    evidence_refs: list[EvidenceReference]
    observation_ids: list[Identifier]
    decision_ids: list[TaskId]
    target: AcademicTarget
    property_id: Identifier
    value: AcademicValue
    character_scope: Identifier
    semantics: AcademicRuleSemantics
    execution_support: Literal["typed", "report_only"] = "typed"
    status: Literal["verified", "pending_conflict", "pending_condition", "check_only"]
    reason: str

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if not self.source_rule_ids and not self.decision_ids:
            raise ValueError("effective rule requires source or decision provenance")
        if self.source_kind != "brief_explicit" and not self.decision_ids:
            raise ValueError("non-Brief rule requires explicit user confirmation")
        if self.source_kind == "template_observation_confirmed" and not self.observation_ids:
            raise ValueError("template rule requires actual observation references")
        if self.source_kind != "template_observation_confirmed" and not self.evidence_refs:
            raise ValueError("text rule requires source evidence")
        if self.status == "verified" and (self.semantics.condition or self.semantics.constraint.operator != "eq" or self.execution_support != "typed"):
            raise ValueError("unresolved condition or constraint cannot be verified")
        from brief_parser.compilers.academic_scope import base_scope, intersection
        from brief_parser.domain.academic_format import finite_value
        base = base_scope(self.target.semantic_role, self.property_id, self.character_scope)
        if intersection(base, self.semantics.scope) != self.semantics.scope:
            raise ValueError("effective scope exceeds declared object or characters")
        if self.target.selector == "semantic_role" and self.semantics.scope != base:
            raise ValueError("filtered effective rule requires a scoped selector")
        if not finite_value(self.value.normalized):
            raise ValueError("effective rule value must be finite")
        constraint = self.semantics.constraint
        expected = ({"min": constraint.lower, "max": constraint.upper} if constraint.operator == "between"
                    else {"min": constraint.lower} if constraint.operator == "gte"
                    else {"max": constraint.upper} if constraint.operator == "lte" else None)
        if expected is not None and self.value.normalized != expected:
            raise ValueError("effective value differs from constraint bounds")
        if self.execution_support == "typed" and constraint.operator == "eq":
            from brief_parser.validators.academic_decisions import validate_format_value
            validate_format_value(self.property_id, self.value.normalized, self.value.unit)
        return self


class AcademicDecisionSnapshot(StrictModel):
    schema_version: Literal["academic-decision-snapshot/1.0"] = "academic-decision-snapshot/1.0"
    compiler_version: Literal["academic-decisions/1.0"] = "academic-decisions/1.0"
    snapshot_id: Sha256Hex
    parent_snapshot_id: Sha256Hex | None
    revision: Annotated[int, Field(ge=0, le=256)]
    task_id: TaskId
    initial_version_id: TaskId
    source_bundle_sha256: Sha256Hex
    source_artifact_id: Identifier
    source_artifact_version: int
    domain_pack: DomainPackRef
    submission_context: SubmissionContext | None
    events: list[AcademicDecisionEvent]
    decision_effects: list[AcademicDecisionEffect]
    rules: list[AcademicEffectiveRule]
    issues: list[AcademicFormatIssue]
    relations: list[AcademicRuleRelation]
    conflicts: list[AcademicRuleConflict]
    fragments: list[AcademicRuleFragment]
    questions: list[AcademicQuestion]
    excluded_source_rule_ids: list[Identifier]
    scope_note: str = "这是解析侧规则快照；verified 仍需编辑器能力与论文目标定位验证，不代表论文已修改。"

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.revision != len(self.events) or len({item.decision_id for item in self.events}) != self.revision:
            raise ValueError("decision revision or event IDs are inconsistent")
        if self.revision > 0 and self.parent_snapshot_id != self.events[-1].request.expected_snapshot_id:
            raise ValueError("snapshot parent differs from submitted decision base")
        if self.revision == 0 and self.parent_snapshot_id is not None:
            raise ValueError("initial snapshot cannot have a parent")
        if any(event.task_id != self.task_id or event.source_bundle_sha256 != self.source_bundle_sha256 for event in self.events):
            raise ValueError("decision belongs to another task or Brief")
        from brief_parser.compilers.academic_scope import analyze_rules
        if (self.relations, self.conflicts, self.fragments) != analyze_rules(self.rules):
            raise ValueError("effective scope analysis differs from rules")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules) or len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError("snapshot repeats rules or questions")
        if [effect.decision_id for effect in self.decision_effects] != [event.decision_id for event in self.events]:
            raise ValueError("snapshot effects differ from decision history")
        ids = {event.decision_id for event in self.events}
        if any(set(rule.decision_ids) - ids for rule in self.rules):
            raise ValueError("effective rule references an unknown decision")
        for rule in self.rules:
            related = [item for item in self.conflicts if rule.rule_id in item.rule_ids]
            expected_status = ("pending_conflict" if any(item.certainty == "definite" for item in related)
                               else "pending_condition" if related or rule.semantics.condition
                               else "check_only" if rule.semantics.constraint.operator != "eq" or rule.execution_support == "report_only" else "verified")
            if rule.status != expected_status:
                raise ValueError("effective rule status differs from scope analysis")
        if content_hash(self.model_dump(mode="json", exclude={"snapshot_id"})) != self.snapshot_id:
            raise ValueError("decision snapshot hash differs from payload")
        return self
