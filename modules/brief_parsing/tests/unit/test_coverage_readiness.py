import pytest

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.evidence_index import EvidenceIndexBuilder
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.domain.enums import Readiness
from brief_parser.domain.foundation import (
    CoverageClassification,
    ReadinessReasonCode,
)
from brief_parser.validators.coverage import CoverageLedgerBuilder
from brief_parser.validators.readiness import ReadinessPolicy


def _foundation():  # type: ignore[no-untyped-def]
    source = FileSecurityValidator().secure_text(
        "品牌为示例品牌。\n必须在片尾出现行动号召。",
        source_id="src_coverage",
        client_source_id="brief",
    )
    document = DocumentIngestor().ingest(source)
    segmentation = ClauseSegmenter().segment(document)
    evidence = EvidenceIndexBuilder().build(document, segmentation)
    return segmentation, evidence


def test_complete_coverage_produces_complete_readiness() -> None:
    segmentation, evidence = _foundation()
    classifications = {
        segmentation.clauses[0].clause_id: CoverageClassification.FACT,
        segmentation.clauses[1].clause_id: CoverageClassification.REQUIREMENT,
    }
    ledger = CoverageLedgerBuilder().build(
        segmentation,
        evidence,
        classifications=classifications,
    )
    policy = ReadinessPolicy()

    assessment = policy.evaluate(policy.signals_from_ledger(ledger))

    assert ledger.coverage_ratio == 1.0
    assert assessment.readiness == Readiness.COMPLETE
    assert assessment.reason_codes == []


def test_noncritical_uncertainty_produces_usable_with_warnings() -> None:
    segmentation, evidence = _foundation()
    classifications = {
        clause.clause_id: CoverageClassification.REQUIREMENT
        for clause in segmentation.clauses
    }
    ledger = CoverageLedgerBuilder().build(
        segmentation,
        evidence,
        classifications=classifications,
    )
    policy = ReadinessPolicy()
    signals = policy.signals_from_ledger(ledger, noncritical_unresolved_count=1)

    assessment = policy.evaluate(signals)

    assert assessment.readiness == Readiness.USABLE_WITH_WARNINGS
    assert assessment.reason_codes == [ReadinessReasonCode.NONCRITICAL_UNRESOLVED]


def test_coverage_gap_and_blocker_produce_incomplete() -> None:
    segmentation, evidence = _foundation()
    classifications = {
        segmentation.clauses[0].clause_id: CoverageClassification.FACT,
    }
    ledger = CoverageLedgerBuilder().build(
        segmentation,
        evidence,
        classifications=classifications,
    )
    policy = ReadinessPolicy()
    signals = policy.signals_from_ledger(ledger, blocker_count=1)

    assessment = policy.evaluate(signals)

    assert assessment.readiness == Readiness.INCOMPLETE
    assert assessment.reason_codes == [
        ReadinessReasonCode.COVERAGE_BELOW_THRESHOLD,
        ReadinessReasonCode.BLOCKER_CONFLICT,
    ]


def test_token_budget_exhaustion_is_an_explicit_blocker() -> None:
    segmentation, evidence = _foundation()
    classifications = {
        clause.clause_id: CoverageClassification.REQUIREMENT
        for clause in segmentation.clauses
    }
    ledger = CoverageLedgerBuilder().build(
        segmentation,
        evidence,
        classifications=classifications,
    )
    policy = ReadinessPolicy()
    signals = policy.signals_from_ledger(ledger, job_token_budget_exceeded=True)

    assessment = policy.evaluate(signals)

    assert assessment.readiness == Readiness.INCOMPLETE
    assert assessment.reason_codes == [ReadinessReasonCode.JOB_TOKEN_BUDGET_EXCEEDED]


def test_unknown_clause_classification_is_rejected() -> None:
    segmentation, evidence = _foundation()

    with pytest.raises(ValueError, match="unknown clauses"):
        CoverageLedgerBuilder().build(
            segmentation,
            evidence,
            classifications={"cl_missing": CoverageClassification.CONTEXT},
        )
