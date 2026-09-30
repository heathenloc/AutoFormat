"""Provider candidate schemas validated before deterministic IR assembly."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import DownstreamPolicy, Modality, Operator, Priority, Severity
from brief_parser.domain.foundation import CoverageClassification


class CandidateValue(StrictModel):
    type: Identifier
    text: str | None
    amount: float | None
    range_end: float | None
    unit: Identifier | None
    items: list[str]

    @model_validator(mode="after")
    def require_value(self) -> Self:
        amount = self.amount
        if self.text is None and amount is None and not self.items:
            raise ValueError("candidate value requires text, amount, or items")
        if self.range_end is not None and amount is None:
            raise ValueError("range_end requires amount")
        if self.range_end is not None and amount is not None and self.range_end < amount:
            raise ValueError("range_end must be greater than or equal to amount")
        return self


class CandidateItem(StrictModel):
    candidate_id: Identifier
    label: Annotated[str, Field(min_length=1)]
    value: CandidateValue
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]


class CandidateReference(CandidateItem):
    relation: Literal["inspiration", "may_emulate", "must_not_copy", "context"]


class CandidateScope(StrictModel):
    applies_to: list[Identifier]
    excludes: list[Identifier]


class CandidateRequirement(StrictModel):
    candidate_id: Identifier
    semantic_key: Identifier
    category: Identifier
    custom_category: str | None
    label: Annotated[str, Field(min_length=1)]
    subject: Identifier
    modality: Modality
    operator: Operator
    value: CandidateValue
    scope: CandidateScope
    condition_text: str | None
    condition_evidence_refs: list[Identifier]
    priority: Priority
    machine_checkability: Identifier
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    downstream_policy: DownstreamPolicy

    @model_validator(mode="after")
    def validate_condition(self) -> Self:
        if self.condition_text is None and self.condition_evidence_refs:
            raise ValueError("condition evidence requires condition_text")
        if self.condition_text is not None and not self.condition_evidence_refs:
            raise ValueError("condition_text requires condition evidence")
        return self


class CandidateConflict(StrictModel):
    topic: Identifier
    severity: Severity
    candidate_ids: Annotated[list[Identifier], Field(min_length=2)]
    reason_code: Identifier
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]


class CandidateUnresolved(StrictModel):
    topic: Identifier
    description: Annotated[str, Field(min_length=1)]
    severity: Severity
    reason_code: Identifier
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    downstream_policy: Literal["do_not_assume", "block"]


class ExtractorOutput(StrictModel):
    facts: list[CandidateItem]
    objectives: list[CandidateItem]
    requirements: list[CandidateRequirement]
    references: list[CandidateReference]
    candidate_conflicts: list[CandidateConflict]
    unresolved_items: list[CandidateUnresolved]

    @model_validator(mode="after")
    def validate_candidate_links(self) -> Self:
        candidate_ids = [
            item.candidate_id
            for group in (self.facts, self.objectives, self.requirements, self.references)
            for item in group
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate ids must be unique within extractor output")
        known_requirements = {item.candidate_id for item in self.requirements}
        for conflict in self.candidate_conflicts:
            missing = set(conflict.candidate_ids) - known_requirements
            if missing:
                raise ValueError(
                    "candidate conflict references unknown requirement candidates: "
                    f"{sorted(missing)}"
                )
        return self


class ClauseAudit(StrictModel):
    clause_id: Identifier
    classification: CoverageClassification
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    reason_code: Identifier


class AuditorOutput(StrictModel):
    clauses: list[ClauseAudit]

    @model_validator(mode="after")
    def validate_unique_clauses(self) -> Self:
        clause_ids = [item.clause_id for item in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("auditor output may classify each clause only once")
        return self


class ResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class ResolverCase(StrictModel):
    dispute_id: Identifier
    reason_code: Identifier
    candidate_ids: Annotated[list[Identifier], Field(min_length=1)]
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]


class ResolutionDecision(StrictModel):
    dispute_id: Identifier
    outcome: ResolutionOutcome
    selected_candidate_ids: list[Identifier]
    reason: Annotated[str, Field(min_length=1)]
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    downstream_policy: DownstreamPolicy

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.outcome == ResolutionOutcome.RESOLVED and not self.selected_candidate_ids:
            raise ValueError("resolved decisions require selected_candidate_ids")
        if self.outcome != ResolutionOutcome.RESOLVED and self.selected_candidate_ids:
            raise ValueError("unresolved or conflict decisions cannot select candidates")
        return self


class ResolverOutput(StrictModel):
    decisions: list[ResolutionDecision]

    @model_validator(mode="after")
    def validate_unique_disputes(self) -> Self:
        dispute_ids = [item.dispute_id for item in self.decisions]
        if len(dispute_ids) != len(set(dispute_ids)):
            raise ValueError("resolver output may decide each dispute only once")
        return self
