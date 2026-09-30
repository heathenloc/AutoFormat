"""Deterministic comparison of Golden annotations and Requirement IR predictions."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from brief_parser.domain.enums import EvidenceMatchStatus, Priority
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.evaluation.cost import estimate_cost
from brief_parser.evaluation.models import (
    EvaluationMetrics,
    EvaluationReport,
    GoldenDataset,
    PredictionRecord,
    PricingTable,
    ReleaseGate,
    ReleaseThresholds,
)


def evaluate_dataset(
    dataset: GoldenDataset,
    predictions: Iterable[PredictionRecord],
    *,
    thresholds: ReleaseThresholds | None = None,
    pricing: PricingTable | None = None,
) -> EvaluationReport:
    configured = thresholds or ReleaseThresholds()
    prediction_by_id: dict[str, PredictionRecord] = {}
    for prediction in predictions:
        if prediction.case_id in prediction_by_id:
            raise ValueError(f"duplicate prediction for {prediction.case_id}")
        prediction_by_id[prediction.case_id] = prediction

    expected_ids = {case.case_id for case in dataset.cases}
    unexpected_ids = sorted(set(prediction_by_id) - expected_ids)
    missing_ids = sorted(expected_ids - set(prediction_by_id))
    invalid_ids: list[str] = []
    valid: dict[str, RequirementIR] = {}
    for case_id in sorted(expected_ids & set(prediction_by_id)):
        raw_ir = prediction_by_id[case_id].requirement_ir
        if raw_ir is None:
            invalid_ids.append(case_id)
            continue
        try:
            valid[case_id] = RequirementIR.model_validate(raw_ir)
        except ValidationError:
            invalid_ids.append(case_id)

    expected_critical: set[tuple[str, str]] = set()
    predicted_critical: set[tuple[str, str]] = set()
    expected_conflicts: set[tuple[str, str]] = set()
    predicted_conflicts: set[tuple[str, str]] = set()
    expected_facts: set[tuple[str, str]] = set()
    predicted_facts: set[tuple[str, str]] = set()
    expected_unresolved: set[tuple[str, str]] = set()
    predicted_unresolved: set[tuple[str, str]] = set()
    evidence_total = 0
    evidence_locatable = 0
    critical_without_evidence = 0
    classified_clauses = 0
    clauses = 0
    prompt_injection_failures = 0
    readiness_matches = 0

    for case in dataset.cases:
        for golden_requirement in case.annotations.requirements:
            if golden_requirement.priority == Priority.CRITICAL:
                expected_critical.add(
                    (case.case_id, golden_requirement.semantic_key)
                )
        expected_conflicts.update(
            (case.case_id, conflict.topic) for conflict in case.annotations.conflicts
        )
        expected_facts.update((case.case_id, fact.label) for fact in case.annotations.facts)
        expected_unresolved.update(
            (case.case_id, item.topic) for item in case.annotations.unresolved
        )

        actual = valid.get(case.case_id)
        if actual is None:
            continue
        readiness_matches += int(actual.readiness == case.annotations.expected_readiness)
        predicted_critical.update(
            (case.case_id, actual_requirement.semantic_key)
            for actual_requirement in actual.requirements
            if actual_requirement.priority == Priority.CRITICAL
        )
        predicted_conflicts.update(
            (case.case_id, conflict.topic) for conflict in actual.conflicts
        )
        predicted_facts.update((case.case_id, fact.label) for fact in actual.facts)
        predicted_unresolved.update(
            (case.case_id, item.topic) for item in actual.unresolved_items
        )
        clauses += actual.quality.clause_count
        classified_clauses += actual.quality.classified_clause_count

        locatable_ids = {
            evidence_id
            for evidence_id, evidence in actual.evidence_index.items()
            if evidence.match_status != EvidenceMatchStatus.INVALID
            and _normalise_text(evidence.quote) in _normalise_text(case.source_text)
        }
        evidence_total += len(actual.evidence_index)
        evidence_locatable += len(locatable_ids)
        for actual_requirement in actual.requirements:
            if actual_requirement.priority == Priority.CRITICAL and not (
                set(actual_requirement.evidence_refs) & locatable_ids
            ):
                critical_without_evidence += 1

        if case.annotations.prompt_injection:
            expected_keys = {
                golden_requirement.semantic_key
                for golden_requirement in case.annotations.requirements
            }
            actual_keys = {
                actual_requirement.semantic_key
                for actual_requirement in actual.requirements
            }
            expected_fact_labels = {
                golden_fact.label for golden_fact in case.annotations.facts
            }
            actual_fact_labels = {actual_fact.label for actual_fact in actual.facts}
            expected_conflict_topics = {
                golden_conflict.topic
                for golden_conflict in case.annotations.conflicts
            }
            actual_conflict_topics = {
                actual_conflict.topic for actual_conflict in actual.conflicts
            }
            expected_unresolved_topics = {
                golden_unresolved.topic
                for golden_unresolved in case.annotations.unresolved
            }
            actual_unresolved_topics = {
                actual_unresolved.topic
                for actual_unresolved in actual.unresolved_items
            }
            if (
                actual_keys != expected_keys
                or actual_fact_labels != expected_fact_labels
                or actual_conflict_topics != expected_conflict_topics
                or actual_unresolved_topics != expected_unresolved_topics
                or actual.readiness != case.annotations.expected_readiness
            ):
                prompt_injection_failures += 1

    total_cases = len(dataset.cases)
    metrics = EvaluationMetrics(
        schema_success_rate=_ratio(len(valid), total_cases),
        evidence_locatable_rate=_ratio(evidence_locatable, evidence_total),
        critical_without_evidence=critical_without_evidence,
        critical_precision=_ratio(
            len(predicted_critical & expected_critical),
            len(predicted_critical),
        ),
        critical_recall=_ratio(
            len(predicted_critical & expected_critical),
            len(expected_critical),
        ),
        conflict_recall=_ratio(
            len(predicted_conflicts & expected_conflicts),
            len(expected_conflicts),
        ),
        classified_clause_coverage=_ratio(classified_clauses, clauses),
        prompt_injection_failures=prompt_injection_failures,
        readiness_accuracy=_ratio(readiness_matches, total_cases),
        fact_recall=_ratio(len(predicted_facts & expected_facts), len(expected_facts)),
        unresolved_recall=_ratio(
            len(predicted_unresolved & expected_unresolved),
            len(expected_unresolved),
        ),
    )
    gates = [
        _gate("schema_success_rate", metrics.schema_success_rate, configured.schema_success_rate),
        _gate(
            "evidence_locatable_rate",
            metrics.evidence_locatable_rate,
            configured.evidence_locatable_rate,
        ),
        _gate(
            "critical_without_evidence",
            float(metrics.critical_without_evidence),
            float(configured.critical_without_evidence_max),
            comparison="lte",
        ),
        _gate("critical_precision", metrics.critical_precision, configured.critical_precision),
        _gate("critical_recall", metrics.critical_recall, configured.critical_recall),
        _gate("conflict_recall", metrics.conflict_recall, configured.conflict_recall),
        _gate(
            "classified_clause_coverage",
            metrics.classified_clause_coverage,
            configured.classified_clause_coverage,
        ),
        _gate(
            "prompt_injection_failures",
            float(metrics.prompt_injection_failures),
            float(configured.prompt_injection_failures_max),
            comparison="lte",
        ),
    ]
    provider_calls = [
        call
        for prediction in prediction_by_id.values()
        for call in prediction.provider_calls
    ]
    return EvaluationReport(
        dataset_version=dataset.dataset_version,
        dataset_case_count=total_cases,
        prediction_count=len(prediction_by_id),
        metrics=metrics,
        gates=gates,
        passed=all(gate.passed for gate in gates)
        and not invalid_ids
        and not missing_ids
        and not unexpected_ids,
        invalid_case_ids=invalid_ids,
        missing_case_ids=missing_ids,
        unexpected_case_ids=unexpected_ids,
        cost=estimate_cost(provider_calls, pricing),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _gate(
    metric: str,
    actual: float,
    threshold: float,
    *,
    comparison: str = "gte",
) -> ReleaseGate:
    if comparison == "lte":
        passed = actual <= threshold
        selected = "lte"
    else:
        passed = actual >= threshold
        selected = "gte"
    return ReleaseGate(
        metric=metric,
        comparison=selected,
        actual=actual,
        threshold=threshold,
        passed=passed,
    )


def _normalise_text(value: str) -> str:
    return " ".join(value.split()).casefold()
