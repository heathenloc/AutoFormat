"""Versioned feedback envelopes. Schema validity never grants edit authority.

Raw text and PDF spans are evidence, not DOCX commands. Only a later trusted
resolver/compiler may turn these records into an editor plan.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, create_model, model_validator

from brief_parser.domain.academic_semantics import AcademicRuleScope
from brief_parser.validators.academic_decisions import (
    ROLES, typed_property, validate_answer_scope, validate_format_value,
)

Id = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")]
Label = Annotated[str, Field(pattern=r"^[^\r\n\x00]{1,200}$")]
PreviewId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Text = Annotated[str, Field(min_length=1, max_length=4096)]
Scope = Literal["selection", "paragraph", "same_kind", "document"]
CharacterScope = Literal["all", "chinese", "latin", "digits", "complex_script", "other"]


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Contract(BaseModel):
    # Keep whitespace in raw input and selected text; offsets depend on it.
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True,
                              validate_default=True, str_strip_whitespace=False)

    @model_validator(mode="after")
    def check_unicode(self) -> Self:
        def visit(value):
            if isinstance(value, str):
                value.encode("utf-8")
            elif isinstance(value, dict):
                for key, item in value.items():
                    visit(key)
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        try:
            visit(self.model_dump(mode="json"))
        except UnicodeError as error:
            raise ValueError("Contract contains invalid Unicode text.") from error
        return self


def _check_digest(model: Contract, field: str) -> None:
    if getattr(model, field) != content_hash(model.model_dump(mode="json", exclude={field})):
        raise ValueError("Contract content hash differs from payload.")


@lru_cache
def _payload_model(model: type[Contract]):
    # Normalize nested defaults before hashing, without skipping any validation
    # on the final model. Root semantic checks run after the hash is calculated.
    return create_model(f"{model.__name__}Payload", __base__=Contract,
        **{name: (definition.annotation, deepcopy(definition))
           for name, definition in model.model_fields.items()})


def seal_contract(model: type[Contract], payload: dict, hash_field: str) -> Contract:
    """Build a canonical server record; this is a checksum, not a signature."""
    if hash_field not in model.model_fields:
        raise ValueError("Contract has no requested hash field.")
    normalized = _payload_model(model).model_validate({**payload, hash_field: "0" * 64}).model_dump(mode="json")
    normalized.pop(hash_field)
    return model.model_validate({**normalized, hash_field: content_hash(normalized)})


def _timestamp(value: str) -> None:
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")


def _unique(values: list) -> None:
    if len(values) != len(set(values)):
        raise ValueError("Contract repeats identifiers.")


class PdfTextSpan(Contract):
    """PDF.js item positions; offsets are UTF-16 code units, not Python indices."""

    page: Annotated[int, Field(ge=1)]
    start_item: Annotated[int, Field(ge=0)]
    start_offset_utf16: Annotated[int, Field(ge=0)]
    end_item: Annotated[int, Field(ge=0)]
    end_offset_utf16: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def check_span(self) -> Self:
        if (self.start_item, self.start_offset_utf16) >= (self.end_item, self.end_offset_utf16):
            raise ValueError("PDF text span is empty or reversed.")
        return self


class SelectionHint(Contract):
    selected_text: Text
    context_before: Annotated[str, Field(max_length=4096)] = ""
    context_after: Annotated[str, Field(max_length=4096)] = ""
    spans: Annotated[list[PdfTextSpan], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def check_spans(self) -> Self:
        if not self.selected_text.strip():
            raise ValueError("Selection must contain text.")
        previous = None
        for span in self.spans:
            start = (span.page, span.start_item, span.start_offset_utf16)
            if previous is not None and start < previous:
                raise ValueError("PDF spans overlap or are not in reading order.")
            previous = (span.page, span.end_item, span.end_offset_utf16)
        return self


class FeedbackVersionContext(Contract):
    """Server-derived identity of one published version, never the task head."""

    schema_version: Literal["feedback-version-context/1.0"]
    context_id: Hash
    task_id: Id
    base_version_id: Id
    base_docx_sha256: Hash
    preview_artifact_id: PreviewId
    preview_pdf_sha256: Hash
    preview_metadata_sha256: Hash
    renderer_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    renderer_version: Label
    page_count: Annotated[int, Field(ge=1)]
    rules_snapshot_id: Label
    brief_version_id: Label
    feedback_rules_snapshot_id: Hash | None = None

    @model_validator(mode="after")
    def check_hash(self) -> Self:
        _check_digest(self, "context_id")
        return self


class FeedbackSubmission(Contract):
    schema_version: Literal["feedback-submission/1.0"]
    request_id: Id
    task_id: Id
    base_version_id: Id
    expected_base_docx_sha256: Hash
    expected_context_id: Hash
    preview_artifact_id: PreviewId
    expected_preview_pdf_sha256: Hash
    raw_text: Text
    requested_scope: Scope = "selection"
    selection: SelectionHint | None = None

    @model_validator(mode="after")
    def check_input(self) -> Self:
        if not self.raw_text.strip():
            raise ValueError("Feedback must contain text.")
        if self.selection is None and self.requested_scope != "document":
            raise ValueError("Local or same-kind feedback requires a selection hint.")
        return self


class DocxTextRange(Contract):
    object_id: Key
    start_utf16: Annotated[int, Field(ge=0)]
    length_utf16: Annotated[int, Field(ge=1)]
    matched_text: Text

    @model_validator(mode="after")
    def check_length(self) -> Self:
        if len(self.matched_text.encode("utf-16-le")) // 2 != self.length_utf16:
            raise ValueError("DOCX character range differs from matched UTF-16 text.")
        return self


class SelectionAnchor(Contract):
    """New generation; the existing prototype selection-anchor/1.0 is preserved."""

    schema_version: Literal["selection-anchor/1.1"]
    anchor_id: Hash
    task_id: Id
    base_version_id: Id
    base_docx_sha256: Hash
    preview_artifact_id: PreviewId
    preview_pdf_sha256: Hash
    renderer_id: Key
    renderer_version: Label
    selection: SelectionHint
    ranges: Annotated[list[DocxTextRange], Field(min_length=1, max_length=64)]
    status: Literal["ready"]

    @model_validator(mode="after")
    def check_anchor(self) -> Self:
        previous: dict[str, int] = {}
        for span in self.ranges:
            if span.start_utf16 < previous.get(span.object_id, 0):
                raise ValueError("DOCX ranges overlap or are reversed within an object.")
            previous[span.object_id] = span.start_utf16 + span.length_utf16
        _check_digest(self, "anchor_id")
        return self


class TargetCandidate(Contract):
    candidate_id: Key
    object_id: Key
    location_label: Text
    excerpt: Text


class SelectionResolution(Contract):
    schema_version: Literal["selection-resolution/1.0"]
    resolution_id: Hash
    feedback_id: Id
    version_context_id: Hash
    status: Literal["ready", "ambiguous", "stale_base_version", "stale_preview",
                    "unsupported_target", "needs_user_input"]
    anchor: SelectionAnchor | None = None
    candidates: Annotated[list[TargetCandidate], Field(max_length=256)] = Field(default_factory=list)
    reason: Text

    @model_validator(mode="after")
    def check_resolution(self) -> Self:
        if (self.status == "ready") != (self.anchor is not None):
            raise ValueError("Only a ready resolution may carry an anchor.")
        if self.status == "ready" and self.candidates:
            raise ValueError("Ready resolution cannot also request target selection.")
        _unique([candidate.candidate_id for candidate in self.candidates])
        _check_digest(self, "resolution_id")
        return self


class SelectionTargetConfirmation(Contract):
    """Target-only decision before feedback parsing exists; no edit permission."""

    schema_version: Literal["selection-target-confirmation/1.0"]
    request_id: Id
    task_id: Id
    base_version_id: Id
    feedback_id: Id
    expected_base_docx_sha256: Hash
    expected_context_id: Hash
    expected_resolution_id: Hash
    candidate_id: Hash
    raw_answer: Text

    @model_validator(mode="after")
    def check_answer(self) -> Self:
        if not self.raw_answer.strip():
            raise ValueError("Target confirmation must contain an explicit answer.")
        return self


class FormatValue(Contract):
    normalized: JsonValue
    unit: Annotated[str, Field(max_length=32)] | None = None


class FeedbackRuleCandidate(Contract):
    candidate_id: Key
    property_id: Key
    value: FormatValue
    requested_scope: Scope
    semantic_role: Key | None = None
    character_scope: CharacterScope = "all"
    applicability_scope: AcademicRuleScope | None = None

    @model_validator(mode="after")
    def check_rule(self) -> Self:
        validate_format_value(self.property_id, self.value.normalized, self.value.unit)
        if self.semantic_role is not None and self.semantic_role not in ROLES | {"table_cell"}:
            raise ValueError("Feedback uses an unregistered semantic role.")
        if self.requested_scope == "same_kind" and self.semantic_role is None:
            raise ValueError("Same-kind rule needs an explicit semantic role.")
        if self.applicability_scope is not None:
            validate_answer_scope(self.applicability_scope)
            from brief_parser.compilers.academic_scope import base_scope, intersection
            base = base_scope(self.semantic_role or "document_text", self.property_id, self.character_scope)
            if intersection(base, self.applicability_scope) != self.applicability_scope:
                raise ValueError("Applicability exceeds the declared role or characters.")
        return self


class FeedbackPartialRule(Contract):
    """Fields understood so far; never a candidate that may be executed."""

    candidate_id: Key
    property_id: Key | None = None
    value: FormatValue | None = None
    semantic_role: Key | None = None
    requested_scope: Scope | None = None

    @model_validator(mode="after")
    def check_partial(self) -> Self:
        if self.property_id is not None and not typed_property(self.property_id):
            raise ValueError("Partial feedback uses an unregistered property.")
        if self.value is not None:
            if self.property_id is None:
                raise ValueError("Partial value requires a known property.")
            validate_format_value(self.property_id, self.value.normalized, self.value.unit)
        if self.semantic_role is not None and self.semantic_role not in ROLES | {"table_cell"}:
            raise ValueError("Partial feedback uses an unregistered role.")
        return self


def property_minimum_unit(property_id: str) -> str:
    """P0 capability vocabulary; the editor must still prove actual support."""
    if property_id.startswith("font."):
        return "character"
    if property_id.startswith("paragraph."):
        return "paragraph"
    if property_id.startswith(("page.", "page_number.", "section.")):
        return "section"
    if property_id == "table.border_style":
        return "table"
    if property_id == "document.position":
        return "region"
    return "field_or_object"


class ScopeReview(Contract):
    """Actual minimum Word unit is distinct from the user's requested scope."""

    review_id: Hash
    candidate_id: Key
    requested_scope: Scope
    effective_scope: Scope
    minimum_unit: Literal["character", "paragraph", "section", "table", "region", "field_or_object", "document"]
    target_ids: Annotated[list[Key], Field(min_length=1, max_length=5000)]
    estimated_affected_count: Annotated[int, Field(ge=1, le=5000)]
    requires_confirmation: bool
    reason: Text

    @model_validator(mode="after")
    def check_review(self) -> Self:
        _unique(self.target_ids)
        if self.estimated_affected_count != len(self.target_ids):
            raise ValueError("Affected count differs from actual target list.")
        if self.effective_scope == "selection" and self.minimum_unit != "character":
            raise ValueError("A Word structure property cannot pretend to edit only selected characters.")
        if self.effective_scope == "paragraph" and self.minimum_unit not in {"character", "paragraph"}:
            raise ValueError("Paragraph scope cannot contain a larger minimum Word unit.")
        # Paragraph-level promotion is displayed before submission; wider scope
        # changes need an explicit confirmation in the later processing stage.
        if (self.effective_scope != self.requested_scope
                and (self.requested_scope, self.effective_scope) != ("selection", "paragraph")
                and not self.requires_confirmation):
            raise ValueError("Expanded scope requires confirmation.")
        _check_digest(self, "review_id")
        return self


class FeedbackConflict(Contract):
    conflict_id: Key
    candidate_id: Key
    existing_rule_ids: Annotated[list[Key], Field(min_length=1, max_length=512)]
    property_id: Key
    affected_target_ids: Annotated[list[Key], Field(min_length=1, max_length=5000)]
    reason: Text

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        _unique(self.existing_rule_ids)
        _unique(self.affected_target_ids)
        return self


class FeedbackParseResult(Contract):
    schema_version: Literal["feedback-parse-result/1.0"]
    result_id: Hash
    task_id: Id
    feedback_id: Id
    version_context_id: Hash
    source_submission_sha256: Hash
    parser_id: Key
    parser_version: Key
    kind: Literal["execution_defect", "new_rule", "clarification_needed", "question", "out_of_scope"]
    candidates: Annotated[list[FeedbackRuleCandidate], Field(max_length=64)] = Field(default_factory=list)
    understood: Annotated[list[FeedbackPartialRule], Field(max_length=64)] = Field(default_factory=list)
    existing_rule_ids: Annotated[list[Key], Field(max_length=512)] = Field(default_factory=list)
    missing_fields: Annotated[list[Key], Field(max_length=64)] = Field(default_factory=list)
    scope_reviews: Annotated[list[ScopeReview], Field(max_length=64)] = Field(default_factory=list)
    conflicts: Annotated[list[FeedbackConflict], Field(max_length=64)] = Field(default_factory=list)
    reason: Text

    @model_validator(mode="after")
    def check_result(self) -> Self:
        ids = [candidate.candidate_id for candidate in self.candidates]
        _unique(ids)
        _unique([partial.candidate_id for partial in self.understood])
        _unique(self.existing_rule_ids)
        _unique(self.missing_fields)
        _unique([review.candidate_id for review in self.scope_reviews])
        _unique([conflict.conflict_id for conflict in self.conflicts])
        if self.kind == "new_rule" and (not ids or self.missing_fields or self.existing_rule_ids):
            raise ValueError("New rule result needs complete candidates, not defect references.")
        if self.kind == "execution_defect" and (not self.existing_rule_ids or ids or self.missing_fields):
            raise ValueError("Execution defect must refer to existing rules, not invent new ones.")
        if self.kind == "clarification_needed" and not self.missing_fields:
            raise ValueError("Clarification result must identify missing fields.")
        if self.understood and self.kind != "clarification_needed":
            raise ValueError("Partial rules belong only to a clarification result.")
        if self.kind in {"question", "out_of_scope"} and (
                ids or self.existing_rule_ids or self.missing_fields or self.scope_reviews or self.conflicts):
            raise ValueError("Consultations and out-of-scope input cannot carry operations.")
        candidate_map = {candidate.candidate_id: candidate for candidate in self.candidates}
        for review in self.scope_reviews:
            if review.candidate_id not in candidate_map or review.requested_scope != candidate_map[review.candidate_id].requested_scope:
                raise ValueError("Scope review differs from its candidate.")
            if review.minimum_unit != property_minimum_unit(candidate_map[review.candidate_id].property_id):
                raise ValueError("Scope review understates or changes the property's Word unit.")
        for conflict in self.conflicts:
            if conflict.candidate_id not in candidate_map or conflict.property_id != candidate_map[conflict.candidate_id].property_id:
                raise ValueError("Conflict differs from its candidate property.")
        _check_digest(self, "result_id")
        return self


class FeedbackDraftReview(Contract):
    """Read-only pre-submission interpretation; not a saved feedback record."""

    schema_version: Literal["feedback-draft-review/1.0"]
    review_id: Hash
    task_id: Id
    base_version_id: Id
    version_context_id: Hash
    source_submission_sha256: Hash
    parser_id: Key
    parser_version: Key
    kind: Literal["execution_defect", "new_rule", "clarification_needed", "question", "out_of_scope"]
    candidates: Annotated[list[FeedbackRuleCandidate], Field(max_length=64)] = Field(default_factory=list)
    understood: Annotated[list[FeedbackPartialRule], Field(max_length=64)] = Field(default_factory=list)
    missing_fields: Annotated[list[Key], Field(max_length=64)] = Field(default_factory=list)
    scope_reviews: Annotated[list[ScopeReview], Field(max_length=64)] = Field(default_factory=list)
    existing_rule_ids: Annotated[list[Key], Field(max_length=512)] = Field(default_factory=list)
    target_status: Literal["ready", "pending_confirmation", "unavailable", "none"]
    reason: Text

    @model_validator(mode="after")
    def check_review(self) -> Self:
        candidates = {c.candidate_id: c for c in self.candidates}
        _unique([c.candidate_id for c in self.candidates])
        _unique(self.missing_fields)
        for review in self.scope_reviews:
            if (review.candidate_id not in candidates or review.requested_scope != candidates[review.candidate_id].requested_scope
                    or review.minimum_unit != property_minimum_unit(candidates[review.candidate_id].property_id)):
                raise ValueError("Draft scope differs from its candidate.")
        if self.kind == "clarification_needed" and not self.missing_fields:
            raise ValueError("Draft clarification must name missing fields.")
        if self.kind in {"question", "out_of_scope"} and (self.candidates or self.scope_reviews or self.existing_rule_ids):
            raise ValueError("Non-instructions cannot carry operations.")
        _check_digest(self, "review_id")
        return self


class FeedbackAnalysis(Contract):
    schema_version: Literal["feedback-analysis/1.0"]
    analysis_id: Hash
    interpretation: FeedbackParseResult
    selection: SelectionResolution | None = None
    confirmed_review_ids: Annotated[list[Hash], Field(max_length=64)] = Field(default_factory=list)
    decision_count: Annotated[int, Field(ge=0, le=128)] = 0

    @model_validator(mode="after")
    def check_analysis(self) -> Self:
        if self.selection is not None and (self.selection.feedback_id != self.interpretation.feedback_id
                or self.selection.version_context_id != self.interpretation.version_context_id):
            raise ValueError("Analysis selection belongs to another feedback.")
        _unique(self.confirmed_review_ids)
        if not set(self.confirmed_review_ids) <= {r.review_id for r in self.interpretation.scope_reviews}:
            raise ValueError("Confirmed scope is not part of this analysis.")
        _check_digest(self, "analysis_id")
        return self


class FeedbackRequestBase(Contract):
    request_id: Id
    task_id: Id
    base_version_id: Id
    expected_base_docx_sha256: Hash
    expected_context_id: Hash
    feedback_id: Id
    expected_parse_result_id: Hash
    raw_answer: Annotated[str, Field(max_length=4096)] = ""


class SelectTargetAnswer(Contract):
    action: Literal["select_target"]
    expected_resolution_id: Hash
    selected_candidate_ids: Annotated[list[Key], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        _unique(self.selected_candidate_ids)
        return self


class ConfirmScopeAnswer(Contract):
    action: Literal["confirm_scope"]
    accepted_review_ids: Annotated[list[Hash], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        _unique(self.accepted_review_ids)
        return self


class ClarifyFormatAnswer(Contract):
    action: Literal["clarify_format"]
    format: FeedbackRuleCandidate


class FeedbackConfirmationRequest(FeedbackRequestBase):
    schema_version: Literal["feedback-confirmation-request/1.0"]
    answer: Annotated[SelectTargetAnswer | ConfirmScopeAnswer | ClarifyFormatAnswer,
                      Field(discriminator="action")]


class FeedbackDecisionRequest(FeedbackRequestBase):
    schema_version: Literal["feedback-decision-request/1.0"]
    conflict_id: Key
    action: Literal["keep_rule", "local_exception", "update_rule"]


class FeedbackEffectiveRule(Contract):
    rule_id: Key
    feedback_id: Id
    source_submission_sha256: Hash
    parse_result_id: Hash
    origin_version_id: Id
    candidate: FeedbackRuleCandidate
    scope_review: ScopeReview
    anchor: SelectionAnchor | None = None
    resolved_anchor: SelectionAnchor | None = None
    effect: Literal["new_rule", "local_exception", "global_update"]
    decision_id: Id | None = None
    status: Literal["pending_target", "pending_conflict", "verified"]

    @model_validator(mode="after")
    def check_rule(self) -> Self:
        if self.scope_review.candidate_id != self.candidate.candidate_id or self.scope_review.requested_scope != self.candidate.requested_scope:
            raise ValueError("Effective rule differs from its candidate and scope review.")
        if self.scope_review.minimum_unit != property_minimum_unit(self.candidate.property_id):
            raise ValueError("Effective rule changes the property's Word unit.")
        if self.effect != "new_rule" and self.decision_id is None:
            raise ValueError("Exception or global replacement requires a user decision.")
        if self.effect == "local_exception" and self.scope_review.effective_scope not in {"selection", "paragraph"}:
            raise ValueError("Local exception cannot expand to a global scope.")
        if self.effect == "global_update" and self.scope_review.effective_scope not in {"same_kind", "document"}:
            raise ValueError("Global replacement requires an explicitly global scope.")
        if self.scope_review.effective_scope in {"selection", "paragraph"}:
            if self.anchor is None and self.status == "verified":
                raise ValueError("Verified local rule requires a resolved anchor.")
        if self.anchor is not None and self.anchor.base_version_id != self.origin_version_id:
            raise ValueError("Rule anchor belongs to another origin version.")
        if self.resolved_anchor is not None:
            if (self.anchor is None or self.resolved_anchor.task_id != self.anchor.task_id
                    or self.resolved_anchor.selection.selected_text != self.anchor.selection.selected_text):
                raise ValueError("Remapped anchor differs from the source task or selected text.")
        current_anchor = self.resolved_anchor or self.anchor
        if current_anchor is not None and self.scope_review.effective_scope in {"selection", "paragraph"}:
            if set(self.scope_review.target_ids) != {span.object_id for span in current_anchor.ranges}:
                raise ValueError("Local scope targets differ from the resolved anchor.")
        if self.status == "verified" and self.scope_review.requires_confirmation and self.decision_id is None:
            raise ValueError("Unconfirmed expanded scope cannot be verified.")
        return self


class FeedbackRuleSnapshot(Contract):
    """Branch lineage contract; compiler/replay and exception migration come later."""

    schema_version: Literal["feedback-rule-snapshot/1.0"]
    compiler_version: Literal["feedback-rules/1.0"]
    snapshot_id: Hash
    parent_snapshot_id: Hash | None
    task_id: Id
    base_version_id: Id
    base_docx_sha256: Hash
    brief_version_id: Label
    academic_rules_snapshot_id: Label
    rules: Annotated[list[FeedbackEffectiveRule], Field(max_length=512)]
    decision_ids: Annotated[list[Id], Field(max_length=256)]

    @model_validator(mode="after")
    def check_snapshot(self) -> Self:
        _unique([rule.rule_id for rule in self.rules])
        _unique(self.decision_ids)
        for rule in self.rules:
            if rule.decision_id is not None and rule.decision_id not in self.decision_ids:
                raise ValueError("Rule refers to an unlisted decision.")
            if rule.anchor is not None and rule.anchor.task_id != self.task_id:
                raise ValueError("Rule anchor belongs to another task.")
            if rule.status == "verified" and rule.scope_review.effective_scope in {"selection", "paragraph"}:
                current = rule.resolved_anchor or rule.anchor
                if (current is None or current.base_version_id != self.base_version_id
                        or current.base_docx_sha256 != self.base_docx_sha256):
                    raise ValueError("Verified local rule has not been resolved against this base version.")
        _check_digest(self, "snapshot_id")
        return self


class FeedbackRecord(Contract):
    schema_version: Literal["feedback-record/1.0"]
    feedback_id: Id
    submission: FeedbackSubmission
    source_submission_sha256: Hash
    created_at: Annotated[str, Field(min_length=1, max_length=64)]
    status: Literal["received"]

    @model_validator(mode="after")
    def check_record(self) -> Self:
        if self.source_submission_sha256 != content_hash(self.submission.model_dump(mode="json")):
            raise ValueError("Stored submission hash differs from original input.")
        _timestamp(self.created_at)
        return self


class FeedbackReceipt(Contract):
    schema_version: Literal["feedback-receipt/1.0"]
    task_id: Id
    base_version_id: Id
    feedback_id: Id
    request_id: Id
    version_context_id: Hash
    source_submission_sha256: Hash
    created_at: Annotated[str, Field(min_length=1, max_length=64)]
    status: Literal["received"]
    replayed: bool
    next_action: Literal["pending_feedback_processing"]

    @model_validator(mode="after")
    def check_time(self) -> Self:
        _timestamp(self.created_at)
        return self


CONTRACTS = {
    "feedback-version-context/1.0": FeedbackVersionContext,
    "feedback-submission/1.0": FeedbackSubmission,
    "selection-anchor/1.1": SelectionAnchor,
    "selection-resolution/1.0": SelectionResolution,
    "selection-target-confirmation/1.0": SelectionTargetConfirmation,
    "feedback-draft-review/1.0": FeedbackDraftReview,
    "feedback-analysis/1.0": FeedbackAnalysis,
    "feedback-parse-result/1.0": FeedbackParseResult,
    "feedback-confirmation-request/1.0": FeedbackConfirmationRequest,
    "feedback-decision-request/1.0": FeedbackDecisionRequest,
    "feedback-rule-snapshot/1.0": FeedbackRuleSnapshot,
    "feedback-record/1.0": FeedbackRecord,
    "feedback-receipt/1.0": FeedbackReceipt,
}


def contract_schema(model: type[Contract]) -> dict:
    """Standalone JSON Schema; semantic/provenance checks still run in Python."""
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    version = schema["properties"]["schema_version"]["const"]
    schema["$id"] = f"https://easyformat.local/contracts/{version}"
    return schema
