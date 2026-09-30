"""Versioned contracts for offline evaluation and release gating."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import Priority, Readiness, Severity
from brief_parser.domain.foundation import CoverageClassification
from brief_parser.domain.pipeline import ProviderCallRecord

Ratio = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class GoldenClause(StrictModel):
    text: Annotated[str, Field(min_length=1)]
    classification: CoverageClassification


class GoldenFact(StrictModel):
    label: Annotated[str, Field(min_length=1)]
    evidence_quotes: Annotated[list[str], Field(min_length=1)]


class GoldenRequirement(StrictModel):
    semantic_key: Identifier
    priority: Priority
    evidence_quotes: Annotated[list[str], Field(min_length=1)]


class GoldenConflict(StrictModel):
    topic: Identifier
    severity: Severity


class GoldenUnresolved(StrictModel):
    topic: Identifier
    severity: Severity


class GoldenAnnotations(StrictModel):
    clause_ledger: Annotated[list[GoldenClause], Field(min_length=1)]
    facts: list[GoldenFact] = Field(default_factory=list)
    requirements: list[GoldenRequirement] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    conflicts: list[GoldenConflict] = Field(default_factory=list)
    unresolved: list[GoldenUnresolved] = Field(default_factory=list)
    expected_readiness: Readiness
    prompt_injection: bool = False

    @model_validator(mode="after")
    def validate_annotation_links(self) -> Self:
        declared = set(self.evidence_quotes)
        cited = {
            quote
            for item in self.facts
            for quote in item.evidence_quotes
        }
        cited.update(
            quote
            for item in self.requirements
            for quote in item.evidence_quotes
        )
        missing = cited - declared
        if missing:
            raise ValueError(f"annotation evidence is not declared: {sorted(missing)}")
        return self


class GoldenCase(StrictModel):
    case_id: Identifier
    category: Literal["advertising", "edge", "general"]
    locale: str = "zh-CN"
    domain_pack_id: Identifier
    domain_pack_version: str
    requested_task_types: Annotated[list[Identifier], Field(min_length=1)]
    source_text: Annotated[str, Field(min_length=1)]
    annotations: GoldenAnnotations

    @model_validator(mode="after")
    def validate_source_links(self) -> Self:
        source = _normalise_text(self.source_text)
        missing_clauses = [
            item.text
            for item in self.annotations.clause_ledger
            if _normalise_text(item.text) not in source
        ]
        if missing_clauses:
            raise ValueError(f"annotated clauses are not in source: {missing_clauses}")
        missing_evidence = [
            quote
            for quote in self.annotations.evidence_quotes
            if _normalise_text(quote) not in source
        ]
        if missing_evidence:
            raise ValueError(f"annotated evidence is not in source: {missing_evidence}")
        return self


class GoldenDataset(StrictModel):
    dataset_version: Literal["golden-dataset/1.0"] = "golden-dataset/1.0"
    provenance: Literal["synthetic", "public_license", "deidentified"]
    cases: Annotated[list[GoldenCase], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_cases(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("golden case ids must be unique")
        return self


class PredictionRecord(StrictModel):
    case_id: Identifier
    requirement_ir: dict[str, Any] | None = None
    provider_calls: list[ProviderCallRecord] = Field(default_factory=list)
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.requirement_ir is None and self.error_code is None:
            raise ValueError("prediction requires requirement_ir or error_code")
        if self.requirement_ir is not None and self.error_code is not None:
            raise ValueError("prediction cannot contain both requirement_ir and error_code")
        return self


class ModelPrice(StrictModel):
    input_usd_per_million_tokens: NonNegativeFloat
    output_usd_per_million_tokens: NonNegativeFloat


class PricingTable(StrictModel):
    pricing_version: Identifier
    currency: Literal["USD"] = "USD"
    models: dict[Identifier, ModelPrice]


class CostReport(StrictModel):
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    estimated_cost_usd: NonNegativeFloat
    priced_call_count: NonNegativeInt
    unpriced_call_count: NonNegativeInt
    unpriced_model_ids: list[Identifier] = Field(default_factory=list)
    pricing_version: Identifier | None = None


class ReleaseThresholds(StrictModel):
    schema_success_rate: Ratio = 1.0
    evidence_locatable_rate: Ratio = 1.0
    critical_without_evidence_max: NonNegativeInt = 0
    critical_precision: Ratio = 0.99
    critical_recall: Ratio = 0.98
    conflict_recall: Ratio = 0.95
    classified_clause_coverage: Ratio = 0.98
    prompt_injection_failures_max: NonNegativeInt = 0


class EvaluationMetrics(StrictModel):
    schema_success_rate: Ratio
    evidence_locatable_rate: Ratio
    critical_without_evidence: NonNegativeInt
    critical_precision: Ratio
    critical_recall: Ratio
    conflict_recall: Ratio
    classified_clause_coverage: Ratio
    prompt_injection_failures: NonNegativeInt
    readiness_accuracy: Ratio
    fact_recall: Ratio
    unresolved_recall: Ratio


class ReleaseGate(StrictModel):
    metric: Identifier
    comparison: Literal["gte", "lte"]
    actual: NonNegativeFloat
    threshold: NonNegativeFloat
    passed: bool


class EvaluationReport(StrictModel):
    report_version: Literal["evaluation-report/1.0"] = "evaluation-report/1.0"
    dataset_version: str
    dataset_case_count: NonNegativeInt
    prediction_count: NonNegativeInt
    metrics: EvaluationMetrics
    gates: list[ReleaseGate]
    passed: bool
    invalid_case_ids: list[Identifier] = Field(default_factory=list)
    missing_case_ids: list[Identifier] = Field(default_factory=list)
    unexpected_case_ids: list[Identifier] = Field(default_factory=list)
    cost: CostReport | None = None


def _normalise_text(value: str) -> str:
    return " ".join(value.split()).casefold()
