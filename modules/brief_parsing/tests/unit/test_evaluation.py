from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.domain.enums import ModelRole
from brief_parser.domain.pipeline import ProviderCallRecord
from brief_parser.evaluation.cost import estimate_cost
from brief_parser.evaluation.dataset import default_golden_dataset_path, load_golden_dataset
from brief_parser.evaluation.evaluator import evaluate_dataset
from brief_parser.evaluation.load import LoadProbeConfig, run_load_probe
from brief_parser.evaluation.models import (
    GoldenAnnotations,
    GoldenCase,
    GoldenClause,
    GoldenDataset,
    GoldenRequirement,
    ModelPrice,
    PredictionRecord,
    PricingTable,
)
from tests.factories import requirement_ir_payload

DATASET = Path(__file__).resolve().parents[2] / "evals" / "golden" / "v1" / "dataset.json"


def _single_case_dataset() -> GoldenDataset:
    quote = "成片时长不得超过60秒"
    return GoldenDataset(
        provenance="synthetic",
        cases=[
            GoldenCase(
                case_id="case-duration",
                category="advertising",
                domain_pack_id="advertising_brief",
                domain_pack_version="1.0.0",
                requested_task_types=["write_ad_script"],
                source_text=quote,
                annotations=GoldenAnnotations(
                    clause_ledger=[
                        GoldenClause(text=quote, classification="requirement")
                    ],
                    requirements=[
                        GoldenRequirement(
                            semantic_key="duration.primary_video.maximum",
                            priority="critical",
                            evidence_quotes=[quote],
                        )
                    ],
                    evidence_quotes=[quote],
                    expected_readiness="complete",
                ),
            )
        ],
    )


def test_checked_in_dataset_expands_to_required_distribution() -> None:
    dataset = load_golden_dataset(DATASET)

    assert len(dataset.cases) == 100
    assert sum(case.category == "advertising" for case in dataset.cases) == 60
    assert sum(case.category == "edge" for case in dataset.cases) == 20
    assert sum(case.category == "general" for case in dataset.cases) == 20
    assert len({case.source_text for case in dataset.cases}) == 100
    assert default_golden_dataset_path() == DATASET


def test_golden_clause_annotations_align_with_actual_segmentation() -> None:
    dataset = load_golden_dataset(DATASET)
    security = FileSecurityValidator()
    ingestor = DocumentIngestor()
    segmenter = ClauseSegmenter()

    for case in dataset.cases:
        source = security.secure_text(
            case.source_text,
            source_id="src_eval",
            client_source_id=case.case_id,
        )
        clauses = segmenter.segment(ingestor.ingest(source)).clauses
        expected = case.annotations.clause_ledger
        assert len(clauses) == len(expected), case.case_id
        for clause, annotation in zip(clauses, expected, strict=True):
            assert annotation.text in clause.raw_text, case.case_id


def test_evaluator_passes_a_matching_evidence_backed_prediction() -> None:
    report = evaluate_dataset(
        _single_case_dataset(),
        [
            PredictionRecord(
                case_id="case-duration",
                requirement_ir=requirement_ir_payload(),
            )
        ],
    )

    assert report.passed is True
    assert report.metrics.schema_success_rate == 1
    assert report.metrics.critical_precision == 1
    assert report.metrics.critical_recall == 1
    assert report.metrics.evidence_locatable_rate == 1


def test_evaluator_rejects_unlocatable_critical_evidence() -> None:
    payload = requirement_ir_payload()
    bad_quote = "来源中不存在的证据"
    evidence = payload["evidence_index"]["ev_duration"]  # type: ignore[index]
    evidence["quote"] = bad_quote  # type: ignore[index]
    evidence["quote_sha256"] = sha256(bad_quote.encode("utf-8")).hexdigest()  # type: ignore[index]

    report = evaluate_dataset(
        _single_case_dataset(),
        [PredictionRecord(case_id="case-duration", requirement_ir=payload)],
    )

    assert report.passed is False
    assert report.metrics.evidence_locatable_rate == 0
    assert report.metrics.critical_without_evidence == 1


def test_cost_report_requires_explicit_prices_and_reports_unpriced_models() -> None:
    call = ProviderCallRecord(
        role=ModelRole.EXTRACTOR,
        provider_alias="synthetic",
        model_id="model-a",
        provider_request_id=None,
        completion_status="completed",
        input_tokens=1_000_000,
        output_tokens=500_000,
        latency_ms=1,
        retry_count=0,
    )
    priced = estimate_cost(
        [call],
        PricingTable(
            pricing_version="synthetic-1",
            models={
                "model-a": ModelPrice(
                    input_usd_per_million_tokens=2,
                    output_usd_per_million_tokens=4,
                )
            },
        ),
    )
    unpriced = estimate_cost([call], None)

    assert priced.estimated_cost_usd == 4
    assert priced.unpriced_call_count == 0
    assert unpriced.estimated_cost_usd == 0
    assert unpriced.unpriced_model_ids == ["model-a"]


async def test_load_probe_reports_failures_without_hiding_latency() -> None:
    async def operation(ordinal: int) -> object:
        if ordinal == 1:
            raise RuntimeError("synthetic failure")
        return object()

    report = await run_load_probe(
        operation,
        LoadProbeConfig(request_count=3, concurrency=2, max_p95_ms=30_000),
    )

    assert report.succeeded == 2
    assert report.failed == 1
    assert report.passed is False
    assert report.p95_ms >= 0
