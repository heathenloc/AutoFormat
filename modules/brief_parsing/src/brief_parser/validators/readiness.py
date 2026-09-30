"""Deterministic readiness policy and stable reason-code precedence."""

from __future__ import annotations

from brief_parser.domain.enums import Readiness
from brief_parser.domain.foundation import (
    CoverageLedger,
    ReadinessAssessment,
    ReadinessReasonCode,
    ReadinessSignals,
)


class ReadinessPolicy:
    def __init__(self, *, coverage_threshold: float = 0.98) -> None:
        if not 0.0 <= coverage_threshold <= 1.0:
            raise ValueError("coverage_threshold must be between zero and one")
        self._coverage_threshold = coverage_threshold

    def signals_from_ledger(
        self,
        ledger: CoverageLedger,
        **overrides: int | float | bool,
    ) -> ReadinessSignals:
        values: dict[str, int | float | bool] = {
            "clause_count": ledger.clause_count,
            "coverage_ratio": ledger.coverage_ratio,
        }
        values.update(overrides)
        return ReadinessSignals.model_validate(values)

    def evaluate(self, signals: ReadinessSignals) -> ReadinessAssessment:
        blockers: list[ReadinessReasonCode] = []
        warnings: list[ReadinessReasonCode] = []

        if signals.clause_count == 0:
            blockers.append(ReadinessReasonCode.NO_CLAUSES)
        if signals.coverage_ratio < self._coverage_threshold:
            blockers.append(ReadinessReasonCode.COVERAGE_BELOW_THRESHOLD)
        if (
            signals.verified_critical_requirement_count
            < signals.critical_requirement_count
        ):
            blockers.append(ReadinessReasonCode.CRITICAL_REQUIREMENT_UNVERIFIED)
        if signals.critical_unresolved_count:
            blockers.append(ReadinessReasonCode.CRITICAL_UNRESOLVED)
        if signals.blocker_count:
            blockers.append(ReadinessReasonCode.BLOCKER_CONFLICT)
        if signals.source_incomplete_count:
            blockers.append(ReadinessReasonCode.SOURCE_INCOMPLETE)
        if signals.critical_invalid_evidence_count:
            blockers.append(ReadinessReasonCode.CRITICAL_EVIDENCE_INVALID)
        if signals.critical_invalid_numeric_count:
            blockers.append(ReadinessReasonCode.CRITICAL_NUMERIC_INVALID)
        if signals.job_token_budget_exceeded:
            blockers.append(ReadinessReasonCode.JOB_TOKEN_BUDGET_EXCEEDED)
        if signals.provider_unverifiable:
            blockers.append(ReadinessReasonCode.PROVIDER_UNVERIFIABLE)

        if signals.noncritical_unresolved_count:
            warnings.append(ReadinessReasonCode.NONCRITICAL_UNRESOLVED)
        if signals.invalid_evidence_count > signals.critical_invalid_evidence_count:
            warnings.append(ReadinessReasonCode.NONCRITICAL_EVIDENCE_INVALID)
        if signals.invalid_numeric_count > signals.critical_invalid_numeric_count:
            warnings.append(ReadinessReasonCode.NONCRITICAL_NUMERIC_INVALID)
        if signals.non_machine_checkable_count:
            warnings.append(ReadinessReasonCode.NON_MACHINE_CHECKABLE)
        if signals.pipeline_warning_count:
            warnings.append(ReadinessReasonCode.PIPELINE_WARNING)

        if blockers:
            readiness = Readiness.INCOMPLETE
        elif warnings:
            readiness = Readiness.USABLE_WITH_WARNINGS
        else:
            readiness = Readiness.COMPLETE
        return ReadinessAssessment(
            readiness=readiness,
            reason_codes=[*blockers, *warnings],
            coverage_threshold=self._coverage_threshold,
        )
