from pathlib import Path

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.evidence_index import EvidenceIndexBuilder
from brief_parser.adapters.fake_provider import FakeFailure, FakeModelProvider
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.adapters.prompt_repository import FilePromptRepository
from brief_parser.application.model_stages import ConditionalResolver
from brief_parser.application.pipeline import BriefParsingPipeline
from brief_parser.domain.candidates import ExtractorOutput, ResolverCase
from brief_parser.domain.enums import ModelRole
from brief_parser.ports.model_provider import ModelRequestContext, TokenUsage
from tests.e2e.test_pipeline import (
    FIXED_TIME,
    MODEL_ROUTES,
    _duration_extractor,
    _foundation,
    _pipeline,
    _request,
    _source,
)

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


class TokenReportingFakeProvider(FakeModelProvider):
    async def structured_generate(self, **kwargs):  # type: ignore[no-untyped-def,override]
        result = await super().structured_generate(**kwargs)
        return result.model_copy(
            update={"token_usage": TokenUsage(input_tokens=40, output_tokens=20)}
        )


async def test_incomplete_auditor_forces_incomplete_result() -> None:
    source = _source("成片时长不得超过60秒。")
    clause = _foundation(source).clauses[0]
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
            ModelRole.AUDITOR: [
                FakeFailure(status="incomplete", reason="synthetic_schema_incomplete")
            ],
        }
    )

    result = await _pipeline(provider).run(_request(source))

    assert result.requirement_ir.readiness == "incomplete"
    assert "provider_unverifiable" in result.requirement_ir.quality.readiness_reason_codes


async def test_invalid_extractor_evidence_keeps_inspectable_incomplete_artifact() -> None:
    source = _source("成片时长不得超过60秒。")
    provider = TokenReportingFakeProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor("ev_not_in_source")],
        }
    )

    result = await _pipeline(provider).run(_request(source))

    assert provider.call_count[ModelRole.EXTRACTOR] == 1
    assert provider.call_count[ModelRole.AUDITOR] == 0
    assert result.requirement_ir.readiness == "incomplete"
    assert result.requirement_ir.requirements == []
    assert result.requirement_ir.quality.provider_call_count == 1
    assert result.requirement_ir.quality.input_tokens == 40
    assert result.requirement_ir.quality.output_tokens == 20
    assert "provider_unverifiable" in result.requirement_ir.quality.readiness_reason_codes
    assert result.requirement_ir.unclassified_content[0].reason_code == (
        "extractor_invalid_evidence"
    )
    assert any(
        stage.stage == "extractor" and stage.reason_code == "invalid_evidence"
        for stage in result.manifest.stages
    )
    assert any(
        stage.stage == "conditional_resolver"
        and stage.status == "skipped"
        for stage in result.manifest.stages
    )


async def test_job_token_budget_stops_later_provider_stages() -> None:
    source = _source("成片时长不得超过60秒。")
    clause = _foundation(source).clauses[0]
    provider = TokenReportingFakeProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
            ModelRole.AUDITOR: [
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "classification": "requirement",
                            "evidence_refs": [clause.evidence_id],
                            "reason_code": "explicit_requirement",
                        }
                    ]
                }
            ],
        }
    )
    pipeline = BriefParsingPipeline(
        provider,
        FilePromptRepository(PROMPTS),
        model_routes=MODEL_ROUTES,
        clock=lambda: FIXED_TIME,
        job_token_budget=50,
    )

    result = await pipeline.run(_request(source))

    assert provider.call_count[ModelRole.EXTRACTOR] == 1
    assert provider.call_count[ModelRole.AUDITOR] == 0
    assert result.requirement_ir.readiness == "incomplete"
    assert result.requirement_ir.quality.input_tokens == 40
    assert result.requirement_ir.quality.output_tokens == 20
    assert "job_token_budget_exceeded" in (
        result.requirement_ir.quality.readiness_reason_codes
    )
    auditor_stage = next(
        stage for stage in result.manifest.stages if stage.stage == "coverage_auditor"
    )
    assert auditor_stage.status == "skipped"
    assert auditor_stage.reason_code == "job_token_budget_exceeded"
    resolver_stage = next(
        stage for stage in result.manifest.stages if stage.stage == "conditional_resolver"
    )
    assert resolver_stage.status == "skipped"
    assert resolver_stage.reason_code == "job_token_budget_exceeded"


async def test_resolver_failure_is_explicit_and_bounded() -> None:
    source = FileSecurityValidator().secure_text(
        "时长必须为60秒。",
        source_id="src_resolver_failure",
        client_source_id="synthetic",
    )
    document = DocumentIngestor().ingest(source)
    segmentation = ClauseSegmenter().segment(document)
    evidence = EvidenceIndexBuilder().build(document, segmentation)
    evidence_id = segmentation.clauses[0].evidence_id
    extractor_output = ExtractorOutput.model_validate(
        _duration_extractor(evidence_id)
    )
    provider = FakeModelProvider(
        {
            ModelRole.RESOLVER: [
                FakeFailure(status="incomplete", reason="synthetic_resolver_failure")
            ]
        }
    )

    result = await ConditionalResolver(
        provider,
        FilePromptRepository(PROMPTS),
    ).resolve(
        cases=[
            ResolverCase(
                dispute_id="dispute_duration",
                reason_code="synthetic_dispute",
                candidate_ids=["cand_duration"],
                evidence_refs=[evidence_id],
                description="synthetic resolver failure case",
            )
        ],
        extractor_output=extractor_output,
        evidence_index=evidence,
        request_context=ModelRequestContext(
            request_id="req_resolver_failure",
            trace_id="trace_resolver_failure",
            source_ids=["src_resolver_failure"],
        ),
    )

    assert result.output is None
    assert result.completion_status == "incomplete"
    assert result.incomplete_reason == "synthetic_resolver_failure"
    assert provider.call_count[ModelRole.RESOLVER] == 1
