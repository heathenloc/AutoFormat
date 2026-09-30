"""Deterministic requirement-foundation contracts used before model inference."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, RawTextModel, StrictModel
from brief_parser.domain.document import BlockKind, DocumentLocator
from brief_parser.domain.enums import Modality, Operator, Readiness
from brief_parser.domain.requirement_ir import EvidenceReference

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class CoverageClassification(StrEnum):
    FACT = "fact"
    OBJECTIVE = "objective"
    REQUIREMENT = "requirement"
    REFERENCE = "reference"
    CONTEXT = "context"
    DUPLICATE = "duplicate"
    UNCLASSIFIED = "unclassified"


class NumericKind(StrEnum):
    NUMBER = "number"
    RANGE = "range"
    PERCENTAGE = "percentage"
    CURRENCY = "currency"


class DatePrecision(StrEnum):
    DAY = "day"


class ReadinessReasonCode(StrEnum):
    NO_CLAUSES = "no_clauses"
    COVERAGE_BELOW_THRESHOLD = "coverage_below_threshold"
    CRITICAL_REQUIREMENT_UNVERIFIED = "critical_requirement_unverified"
    CRITICAL_UNRESOLVED = "critical_unresolved"
    BLOCKER_CONFLICT = "blocker_conflict"
    SOURCE_INCOMPLETE = "source_incomplete"
    CRITICAL_EVIDENCE_INVALID = "critical_evidence_invalid"
    CRITICAL_NUMERIC_INVALID = "critical_numeric_invalid"
    JOB_TOKEN_BUDGET_EXCEEDED = "job_token_budget_exceeded"
    PROVIDER_UNVERIFIABLE = "provider_unverifiable"
    NONCRITICAL_UNRESOLVED = "noncritical_unresolved"
    NONCRITICAL_EVIDENCE_INVALID = "noncritical_evidence_invalid"
    NONCRITICAL_NUMERIC_INVALID = "noncritical_numeric_invalid"
    NON_MACHINE_CHECKABLE = "non_machine_checkable"
    PIPELINE_WARNING = "pipeline_warning"


class Clause(RawTextModel):
    clause_id: Identifier
    source_id: Identifier
    block_id: Identifier
    ordinal: NonNegativeInt
    block_kind: BlockKind
    normalized_start: NonNegativeInt
    normalized_end: PositiveInt
    raw_start: NonNegativeInt
    raw_end: PositiveInt
    normalized_text: Annotated[str, Field(min_length=1)]
    raw_text: Annotated[str, Field(min_length=1)]
    evidence_id: Identifier
    primary_chunk_id: Identifier
    locator: DocumentLocator

    @model_validator(mode="after")
    def validate_spans(self) -> Self:
        if self.normalized_end <= self.normalized_start:
            raise ValueError("clause normalized span must be non-empty")
        if self.raw_end <= self.raw_start:
            raise ValueError("clause raw span must be non-empty")
        if self.normalized_end - self.normalized_start != len(self.normalized_text):
            raise ValueError("clause normalized span length does not match text")
        if self.raw_end - self.raw_start != len(self.raw_text):
            raise ValueError("clause raw span length does not match text")
        return self


class ClauseChunk(StrictModel):
    chunk_id: Identifier
    ordinal: NonNegativeInt
    clause_ids: Annotated[list[Identifier], Field(min_length=1)]
    context_clause_ids: list[Identifier] = Field(default_factory=list)
    estimated_input_tokens: PositiveInt


class ClauseSegmentation(StrictModel):
    clauses: list[Clause]
    chunks: list[ClauseChunk]

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("clause ids must be unique")
        if [clause.ordinal for clause in self.clauses] != list(range(len(self.clauses))):
            raise ValueError("clause ordinals must be contiguous and zero-based")

        chunk_ids = {chunk.chunk_id for chunk in self.chunks}
        primary_ids = [clause_id for chunk in self.chunks for clause_id in chunk.clause_ids]
        if sorted(primary_ids) != sorted(clause_ids):
            raise ValueError("every clause must occur in exactly one primary chunk")
        if len(primary_ids) != len(set(primary_ids)):
            raise ValueError("a clause cannot occur in multiple primary chunks")
        for clause in self.clauses:
            if clause.primary_chunk_id not in chunk_ids:
                raise ValueError("clause references an unknown primary chunk")
            owner = next(
                chunk for chunk in self.chunks if chunk.chunk_id == clause.primary_chunk_id
            )
            if clause.clause_id not in owner.clause_ids:
                raise ValueError("clause primary_chunk_id does not own the clause")
        return self


class RuleSpan(RawTextModel):
    normalized_start: NonNegativeInt
    normalized_end: PositiveInt
    raw_start: NonNegativeInt
    raw_end: PositiveInt
    quote: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_spans(self) -> Self:
        if self.normalized_end <= self.normalized_start:
            raise ValueError("rule normalized span must be non-empty")
        if self.raw_end <= self.raw_start:
            raise ValueError("rule raw span must be non-empty")
        if self.raw_end - self.raw_start != len(self.quote):
            raise ValueError("rule raw span length does not match quote")
        return self


class NumericMention(StrictModel):
    mention_id: Identifier
    kind: NumericKind
    amount: Decimal
    range_end: Decimal | None = None
    unit: Identifier | None = None
    operator: Operator | None = None
    span: RuleSpan

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.kind == NumericKind.RANGE and self.range_end is None:
            raise ValueError("range mentions require range_end")
        if self.kind != NumericKind.RANGE and self.range_end is not None:
            raise ValueError("only range mentions may have range_end")
        if self.range_end is not None and self.range_end < self.amount:
            raise ValueError("range_end must be greater than or equal to amount")
        return self


class DateMention(StrictModel):
    mention_id: Identifier
    value: date
    precision: DatePrecision = DatePrecision.DAY
    operator: Operator | None = None
    span: RuleSpan


class UnitMention(StrictModel):
    mention_id: Identifier
    unit: Identifier
    span: RuleSpan


class ModalityMention(StrictModel):
    mention_id: Identifier
    modality: Modality
    span: RuleSpan


class DeterministicClauseAnalysis(StrictModel):
    clause_id: Identifier
    numeric_mentions: list[NumericMention] = Field(default_factory=list)
    date_mentions: list[DateMention] = Field(default_factory=list)
    unit_mentions: list[UnitMention] = Field(default_factory=list)
    modality_mentions: list[ModalityMention] = Field(default_factory=list)


class CoverageLedgerEntry(StrictModel):
    clause_id: Identifier
    classification: CoverageClassification
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    reason_codes: list[Identifier] = Field(default_factory=list)


class CoverageLedger(StrictModel):
    entries: list[CoverageLedgerEntry]
    clause_count: NonNegativeInt
    classified_clause_count: NonNegativeInt
    unclassified_clause_count: NonNegativeInt
    coverage_ratio: Ratio

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if len(self.entries) != self.clause_count:
            raise ValueError("coverage entry count must equal clause_count")
        if self.classified_clause_count + self.unclassified_clause_count != self.clause_count:
            raise ValueError("coverage counts must sum to clause_count")
        expected = (
            self.classified_clause_count / self.clause_count
            if self.clause_count
            else 0.0
        )
        if abs(self.coverage_ratio - expected) > 1e-12:
            raise ValueError("coverage_ratio does not match coverage counts")
        if len({entry.clause_id for entry in self.entries}) != len(self.entries):
            raise ValueError("coverage ledger may contain each clause only once")
        return self


class ReadinessSignals(StrictModel):
    clause_count: NonNegativeInt
    coverage_ratio: Ratio
    critical_requirement_count: NonNegativeInt = 0
    verified_critical_requirement_count: NonNegativeInt = 0
    critical_unresolved_count: NonNegativeInt = 0
    noncritical_unresolved_count: NonNegativeInt = 0
    blocker_count: NonNegativeInt = 0
    source_incomplete_count: NonNegativeInt = 0
    invalid_evidence_count: NonNegativeInt = 0
    critical_invalid_evidence_count: NonNegativeInt = 0
    invalid_numeric_count: NonNegativeInt = 0
    critical_invalid_numeric_count: NonNegativeInt = 0
    non_machine_checkable_count: NonNegativeInt = 0
    pipeline_warning_count: NonNegativeInt = 0
    job_token_budget_exceeded: bool = False
    provider_unverifiable: bool = False

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.verified_critical_requirement_count > self.critical_requirement_count:
            raise ValueError("verified critical count cannot exceed total critical count")
        if self.critical_invalid_evidence_count > self.invalid_evidence_count:
            raise ValueError("critical invalid evidence cannot exceed invalid evidence")
        if self.critical_invalid_numeric_count > self.invalid_numeric_count:
            raise ValueError("critical invalid numeric cannot exceed invalid numeric")
        return self


class ReadinessAssessment(StrictModel):
    readiness: Readiness
    reason_codes: list[ReadinessReasonCode] = Field(default_factory=list)
    coverage_threshold: Ratio


EvidenceIndex = dict[Identifier, EvidenceReference]
