"""Feedback conflict/compilation contracts; keep historical 1.0 shapes intact."""
from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator
from brief_parser.domain.academic_decisions import AcademicEffectiveRule
from brief_parser.domain.academic_semantics import AcademicRuleFragment

from .feedback_contracts import (Contract, Hash, Id, Key, Label, Text, FormatValue,
    FeedbackAnalysis, FeedbackDecisionRequest, FeedbackParseResult, SelectionAnchor,
    _check_digest, _unique)


class FeedbackRuleBasis(Contract):
    academic_rules_snapshot_id: Label
    rules: Annotated[list[AcademicEffectiveRule], Field(max_length=512)]
    fragments: Annotated[list[AcademicRuleFragment], Field(max_length=20000)]

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        _unique([r.rule_id for r in self.rules])
        _unique([f.fragment_id for f in self.fragments])
        if not {f.rule_id for f in self.fragments} <= {r.rule_id for r in self.rules}:
            raise ValueError("Basis fragment has no source rule.")
        return self


class FeedbackRuleSpan(Contract):
    object_id: Key
    start_utf16: Annotated[int, Field(ge=0)] | None = None
    length_utf16: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def check_span(self) -> Self:
        if (self.start_utf16 is None) != (self.length_utf16 is None):
            raise ValueError("A character range needs both offset and length.")
        return self


class FeedbackCompiledRule(Contract):
    rule_id: Key
    source_kind: Literal["academic", "feedback"]
    source_rule_id: Key
    feedback_id: Id | None = None
    candidate_id: Key | None = None
    origin_version_id: Id
    property_id: Key
    value: FormatValue
    original_requirement: Text
    evidence_quotes: Annotated[list[Text], Field(max_length=512)]
    requested_scope: Literal["selection", "paragraph", "same_kind", "document"]
    anchor: SelectionAnchor | None = None

    @model_validator(mode="after")
    def check_source(self) -> Self:
        if (self.feedback_id is not None and self.candidate_id is not None) != (self.source_kind == "feedback"):
            raise ValueError("Feedback rule needs its original feedback and candidate.")
        if self.source_kind == "academic" and (self.feedback_id is not None or self.candidate_id is not None or self.anchor is not None):
            raise ValueError("Academic rule cannot claim a feedback anchor.")
        return self


class FeedbackRuleFragment(Contract):
    fragment_id: Hash
    rule_id: Key
    property_id: Key
    span: FeedbackRuleSpan
    value: FormatValue
    status: Literal["verified", "pending_conflict", "pending_scope", "pending_basis", "pending_target", "superseded"]
    conflict_ids: Annotated[list[Key], Field(max_length=512)] = Field(default_factory=list)
    decision_ids: Annotated[list[Id], Field(max_length=256)] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_fragment(self) -> Self:
        _unique(self.conflict_ids); _unique(self.decision_ids)
        if self.status == "pending_conflict" and not self.conflict_ids:
            raise ValueError("Blocked fragment needs a conflict reference.")
        _check_digest(self, "fragment_id")
        return self


class FeedbackRuleConflictReview(Contract):
    conflict_id: Key
    feedback_id: Id
    candidate_id: Key
    incoming_rule_id: Key
    existing_rule_id: Key
    property_id: Key
    spans: Annotated[list[FeedbackRuleSpan], Field(min_length=1, max_length=5000)]
    allowed_actions: Annotated[list[Literal["keep_rule", "local_exception", "update_rule"]], Field(min_length=1, max_length=3)]
    resolution: Literal["keep_rule", "local_exception", "update_rule"] | None = None
    decision_id: Id | None = None
    reason: Text

    @model_validator(mode="after")
    def check_resolution(self) -> Self:
        _unique(self.allowed_actions)
        if (self.resolution is None) != (self.decision_id is None) or self.resolution is not None and self.resolution not in self.allowed_actions:
            raise ValueError("Conflict resolution has no authorized decision.")
        return self


class FeedbackRulesDecision(FeedbackDecisionRequest):
    schema_version: Literal["feedback-decision-request/1.1"]
    expected_snapshot_id: Hash


class FeedbackRulesSnapshot(Contract):
    schema_version: Literal["feedback-rule-snapshot/1.1"]
    compiler_version: Literal["feedback-rules/1.1"] = "feedback-rules/1.1"
    snapshot_id: Hash
    task_id: Id
    base_version_id: Id
    base_docx_sha256: Hash
    version_context_id: Hash
    brief_version_id: Label
    academic_rules_snapshot_id: Label
    parent_snapshot_id: Hash | None
    previous_snapshot_id: Hash | None
    revision: Annotated[int, Field(ge=0, le=256)]
    engine_fingerprint: Hash
    basis_available: bool
    inputs: Annotated[list[FeedbackAnalysis], Field(max_length=64)]
    rules: Annotated[list[FeedbackCompiledRule], Field(max_length=1024)]
    fragments: Annotated[list[FeedbackRuleFragment], Field(max_length=20000)]
    conflicts: Annotated[list[FeedbackRuleConflictReview], Field(max_length=256)]
    decision_ids: Annotated[list[Id], Field(max_length=256)]
    decision_requests: Annotated[list[FeedbackRulesDecision], Field(max_length=256)]
    invalidated_decision_ids: Annotated[list[Id], Field(max_length=256)]
    pending_feedback_ids: Annotated[list[Id], Field(max_length=64)]
    status: Literal["ready", "needs_user_input", "no_rule_change"]
    reason: Text

    @model_validator(mode="after")
    def check_snapshot(self) -> Self:
        rules = {r.rule_id: r for r in self.rules}
        _unique([r.rule_id for r in self.rules]); _unique([f.fragment_id for f in self.fragments])
        _unique([i.interpretation.feedback_id for i in self.inputs]); _unique(self.decision_ids)
        _unique([c.conflict_id for c in self.conflicts]); _unique(self.pending_feedback_ids)
        _unique(self.invalidated_decision_ids)
        _unique([d.request_id for d in self.decision_requests])
        if len(self.decision_ids) != len(self.decision_requests):
            raise ValueError("Decision identities and source requests differ.")
        for decision in self.decision_requests:
            if (decision.task_id != self.task_id or decision.base_version_id != self.base_version_id or
                    decision.expected_context_id != self.version_context_id or decision.expected_base_docx_sha256 != self.base_docx_sha256):
                raise ValueError("Snapshot decision belongs to another version.")
        for item in self.inputs:
            if item.interpretation.task_id != self.task_id or item.interpretation.version_context_id != self.version_context_id:
                raise ValueError("Snapshot input belongs to another task/version.")
        for fragment in self.fragments:
            if fragment.rule_id not in rules or not set(fragment.decision_ids) <= set(self.decision_ids):
                raise ValueError("Fragment has an unknown rule/decision.")
            if fragment.value != rules[fragment.rule_id].value:
                raise ValueError("Fragment changed its source rule value.")
        if not set(self.invalidated_decision_ids) <= set(self.decision_ids):
            raise ValueError("Invalidated decision has no source request.")
        for conflict in self.conflicts:
            if conflict.incoming_rule_id not in rules or conflict.existing_rule_id not in rules or conflict.decision_id is not None and conflict.decision_id not in self.decision_ids:
                raise ValueError("Conflict has an unknown rule or decision.")
        if self.status == "ready" and (not self.basis_available or self.pending_feedback_ids or
                any(f.status.startswith("pending_") for f in self.fragments)):
            raise ValueError("Pending rules cannot be declared ready.")
        _check_digest(self, "snapshot_id")
        return self


class FeedbackRulesSnapshotV2(FeedbackRulesSnapshot):
    schema_version: Literal["feedback-rule-snapshot/1.2"]
    compiler_version: Literal["feedback-rules/1.2"] = "feedback-rules/1.2"


class FeedbackRulesReview(Contract):
    schema_version: Literal["feedback-rules-review/1.0"]
    review_id: Hash
    parse_result: FeedbackParseResult
    snapshot: FeedbackRulesSnapshot

    @model_validator(mode="after")
    def check_review(self) -> Self:
        if (self.parse_result.task_id != self.snapshot.task_id or
                self.parse_result.version_context_id != self.snapshot.version_context_id):
            raise ValueError("Rule review belongs to another version.")
        _check_digest(self, "review_id")
        return self


class FeedbackRulesReviewV2(FeedbackRulesReview):
    schema_version: Literal["feedback-rules-review/1.1"]
    snapshot: FeedbackRulesSnapshotV2


RULE_CONTRACTS = {"feedback-rule-snapshot/1.1": FeedbackRulesSnapshot,
    "feedback-rule-snapshot/1.2": FeedbackRulesSnapshotV2,
    "feedback-decision-request/1.1": FeedbackRulesDecision,
    "feedback-rules-review/1.0": FeedbackRulesReview,
    "feedback-rules-review/1.1": FeedbackRulesReviewV2}
