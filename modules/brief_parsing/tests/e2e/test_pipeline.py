from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.fake_provider import FakeFailure, FakeModelProvider
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.adapters.prompt_repository import FilePromptRepository
from brief_parser.application.pipeline import BriefParsingPipeline, ParsePipelineRequest
from brief_parser.domain.candidates import ExtractorOutput
from brief_parser.domain.enums import ModelRole, Priority, Readiness, Severity, VerificationStatus
from brief_parser.domain.pipeline import PipelineResult
from brief_parser.domain.requirement_ir import DomainPackRef
from brief_parser.validators.conflict import ConflictDetector

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
FIXED_TIME = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
MODEL_ROUTES = {
    ModelRole.EXTRACTOR: "fake-extractor-v1",
    ModelRole.AUDITOR: "fake-auditor-v1",
    ModelRole.RESOLVER: "fake-resolver-v1",
}


def _source(text: str, *, source_id: str = "src_pipeline"):  # type: ignore[no-untyped-def]
    return FileSecurityValidator().secure_text(
        text,
        source_id=source_id,
        client_source_id="synthetic-brief",
        language_hints=("zh-CN",),
    )


def _request(source):  # type: ignore[no-untyped-def]
    return ParsePipelineRequest(
        request_id="req_pipeline",
        sources=(source,),
        domain_pack=DomainPackRef(id="advertising_brief", version="1.0.0"),
        requested_task_types=("script", "voice"),
    )


def _foundation(source):  # type: ignore[no-untyped-def]
    document = DocumentIngestor().ingest(source)
    return ClauseSegmenter().segment(document)


def _duration_extractor(evidence_id: str) -> dict[str, object]:
    return {
        "facts": [],
        "objectives": [],
        "requirements": [
            {
                "candidate_id": "cand_duration",
                "semantic_key": "duration.primary_video.maximum",
                "category": "duration",
                "custom_category": None,
                "label": "主视频时长上限",
                "subject": "primary_video",
                "modality": "must",
                "operator": "lte",
                "value": {
                    "type": "duration",
                    "text": None,
                    "amount": 60,
                    "range_end": None,
                    "unit": "second",
                    "items": [],
                },
                "scope": {"applies_to": ["primary_video"], "excludes": []},
                "condition_text": None,
                "condition_evidence_refs": [],
                "priority": "critical",
                "machine_checkability": "text_checkable",
                "evidence_refs": [evidence_id],
                "downstream_policy": "enforce",
            }
        ],
        "references": [],
        "candidate_conflicts": [],
        "unresolved_items": [],
    }


def _auditor(clause_ids: list[str], evidence_ids: list[str]) -> dict[str, object]:
    return {
        "clauses": [
            {
                "clause_id": clause_id,
                "classification": "requirement",
                "evidence_refs": [evidence_id],
                "reason_code": "explicit_requirement",
            }
            for clause_id, evidence_id in zip(clause_ids, evidence_ids, strict=True)
        ]
    }


def _pipeline(provider: FakeModelProvider) -> BriefParsingPipeline:
    return BriefParsingPipeline(
        provider,
        FilePromptRepository(PROMPTS),
        model_routes=MODEL_ROUTES,
        clock=lambda: FIXED_TIME,
    )


async def test_synthetic_brief_produces_verifiable_complete_ir() -> None:
    source = _source("成片时长不得超过60秒。")
    segmentation = _foundation(source)
    clause = segmentation.clauses[0]
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
            ModelRole.AUDITOR: [
                _auditor([clause.clause_id], [clause.evidence_id])
            ],
        }
    )

    result = await _pipeline(provider).run(_request(source))

    requirement = result.requirement_ir.requirements[0]
    assert result.requirement_ir.readiness == Readiness.COMPLETE
    assert requirement.verification_status == VerificationStatus.VERIFIED
    assert requirement.verification_basis == [
        "evidence_exact_match",
        "schema_validated",
        "numeric_rule_match",
        "modality_rule_match",
    ]
    assert requirement.evidence_refs == [clause.evidence_id]
    assert result.requirement_ir.evidence_index[clause.evidence_id].quote == clause.raw_text
    assert result.manifest.request_fingerprint
    assert result.requirement_ir.quality.provider_call_count == 2
    assert PipelineResult.model_validate_json(result.model_dump_json()) == result


async def test_domain_pack_risk_is_a_deterministic_priority_floor() -> None:
    source = _source("成片时长不得超过60秒。")
    clause = _foundation(source).clauses[0]
    candidate = ExtractorOutput.model_validate(_duration_extractor(clause.evidence_id))
    model_output = candidate.model_copy(
        update={
            "requirements": [
                candidate.requirements[0].model_copy(
                    update={"priority": Priority.NORMAL}
                )
            ]
        }
    )
    response = {
        ModelRole.EXTRACTOR: [model_output],
        ModelRole.AUDITOR: [_auditor([clause.clause_id], [clause.evidence_id])],
    }
    request_without_floor = replace(
        _request(source),
        domain_category_ids=("duration",),
    )
    request_with_floor = replace(
        request_without_floor,
        domain_category_risks=(("duration", Priority.CRITICAL),),
    )

    baseline = await _pipeline(FakeModelProvider(response)).run(request_without_floor)
    adjusted = await _pipeline(FakeModelProvider(response)).run(request_with_floor)

    assert baseline.requirement_ir.requirements[0].priority == Priority.NORMAL
    assert adjusted.requirement_ir.requirements[0].priority == Priority.CRITICAL
    assert adjusted.requirement_ir.requirements[0].verification_status == (
        VerificationStatus.VERIFIED
    )
    assert adjusted.manifest.pipeline_version == "1.2.0"
    assert adjusted.manifest.request_fingerprint != baseline.manifest.request_fingerprint


def test_category_risk_floor_applies_before_conflict_severity() -> None:
    output = ExtractorOutput.model_validate(_duration_extractor("ev_synthetic"))
    first = output.requirements[0].model_copy(
        update={"priority": Priority.NORMAL}
    )
    second = first.model_copy(
        update={
            "candidate_id": "cand_second_duration",
            "value": first.value.model_copy(update={"amount": 30}),
        }
    )
    paired = output.model_copy(update={"requirements": [first, second]})

    adjusted = BriefParsingPipeline._apply_category_risk_floor(
        paired,
        {"duration": Priority.HIGH},
    )
    conflicts = ConflictDetector().detect(adjusted)

    assert [item.priority for item in adjusted.requirements] == [
        Priority.HIGH,
        Priority.HIGH,
    ]
    assert len(conflicts) == 1
    assert conflicts[0].severity == Severity.BLOCKER


async def test_duration_only_in_objective_cannot_be_marked_complete() -> None:
    source = _source("制作一条30秒短视频广告。")
    clause = _foundation(source).clauses[0]
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [
                {
                    "facts": [],
                    "objectives": [
                        {
                            "candidate_id": "cand_objective",
                            "label": "制作30秒短视频广告",
                            "value": {
                                "type": "text",
                                "text": "制作30秒短视频广告",
                                "amount": None,
                                "range_end": None,
                                "unit": None,
                                "items": [],
                            },
                            "evidence_refs": [clause.evidence_id],
                        }
                    ],
                    "requirements": [],
                    "references": [],
                    "candidate_conflicts": [],
                    "unresolved_items": [],
                }
            ],
            ModelRole.AUDITOR: [
                {
                    "clauses": [
                        {
                            "clause_id": clause.clause_id,
                            "classification": "objective",
                            "evidence_refs": [clause.evidence_id],
                            "reason_code": "explicit_objective",
                        }
                    ]
                }
            ],
        }
    )

    result = await _pipeline(provider).run(_request(source))

    assert result.requirement_ir.readiness == Readiness.USABLE_WITH_WARNINGS
    assert any(
        item.reason_code == "duration_requirement_gap"
        for item in result.requirement_ir.unresolved_items
    )


async def test_conflicting_cta_is_preserved_and_blocks_readiness() -> None:
    source = _source("行动号召必须为立即购买。\n行动号召必须为了解更多。")
    segmentation = _foundation(source)
    first, second = segmentation.clauses
    extractor = {
        "facts": [],
        "objectives": [],
        "requirements": [
            {
                "candidate_id": candidate_id,
                "semantic_key": "cta.primary.text",
                "category": "cta",
                "custom_category": None,
                "label": "行动号召",
                "subject": "primary_video",
                "modality": "must",
                "operator": "eq",
                "value": {
                    "type": "text",
                    "text": value,
                    "amount": None,
                    "range_end": None,
                    "unit": None,
                    "items": [],
                },
                "scope": {"applies_to": ["primary_video"], "excludes": []},
                "condition_text": None,
                "condition_evidence_refs": [],
                "priority": "critical",
                "machine_checkability": "text_checkable",
                "evidence_refs": [clause.evidence_id],
                "downstream_policy": "enforce",
            }
            for candidate_id, value, clause in (
                ("cand_cta_buy", "立即购买", first),
                ("cand_cta_learn", "了解更多", second),
            )
        ],
        "references": [],
        "candidate_conflicts": [
            {
                "topic": "cta.primary.text",
                "severity": "blocker",
                "candidate_ids": ["cand_cta_buy", "cand_cta_learn"],
                "reason_code": "contradictory_values",
                "evidence_refs": [first.evidence_id, second.evidence_id],
            }
        ],
        "unresolved_items": [],
    }
    chunk_id = segmentation.chunks[0].chunk_id
    from brief_parser.application.ir_assembler import RequirementIRAssembler
    from brief_parser.domain.candidates import CandidateConflict

    namespaced_conflict = CandidateConflict(
        topic="cta.primary.text",
        severity="blocker",
        candidate_ids=[f"{chunk_id}.cand_cta_buy", f"{chunk_id}.cand_cta_learn"],
        reason_code="contradictory_values",
        evidence_refs=[first.evidence_id, second.evidence_id],
    )
    dispute_id = RequirementIRAssembler.dispute_id(namespaced_conflict)
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [extractor],
            ModelRole.AUDITOR: [
                _auditor(
                    [first.clause_id, second.clause_id],
                    [first.evidence_id, second.evidence_id],
                )
            ],
            ModelRole.RESOLVER: [
                {
                    "decisions": [
                        {
                            "dispute_id": dispute_id,
                            "outcome": "resolved",
                            "selected_candidate_ids": [
                                f"{chunk_id}.cand_cta_buy"
                            ],
                            "reason": "synthetic unsupported preference",
                            "evidence_refs": [first.evidence_id, second.evidence_id],
                            "downstream_policy": "block",
                        }
                    ]
                }
            ],
        }
    )

    result = await _pipeline(provider).run(_request(source))

    assert len(result.requirement_ir.requirements) == 2
    assert len(result.requirement_ir.conflicts) == 1
    assert result.requirement_ir.conflicts[0].resolution is None
    assert result.requirement_ir.readiness == Readiness.INCOMPLETE
    assert "blocker_conflict" in result.requirement_ir.quality.readiness_reason_codes
    assert provider.call_count[ModelRole.RESOLVER] == 1


async def test_provider_refusal_returns_incomplete_auditable_ir() -> None:
    source = _source("成片时长不得超过60秒。")
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [
                FakeFailure(status="refused", reason="synthetic safety refusal")
            ]
        }
    )

    result = await _pipeline(provider).run(_request(source))

    assert result.requirement_ir.readiness == Readiness.INCOMPLETE
    assert result.requirement_ir.requirements == []
    assert len(result.requirement_ir.unclassified_content) == 1
    assert "provider_unverifiable" in result.requirement_ir.quality.readiness_reason_codes
    assert provider.call_count[ModelRole.AUDITOR] == 0
    assert provider.call_count[ModelRole.RESOLVER] == 0


async def test_same_request_and_configuration_have_stable_fingerprint() -> None:
    source = _source("成片时长不得超过60秒。")
    clause = _foundation(source).clauses[0]

    def provider() -> FakeModelProvider:
        return FakeModelProvider(
            {
                ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
                ModelRole.AUDITOR: [
                    _auditor([clause.clause_id], [clause.evidence_id])
                ],
            }
        )

    first = await _pipeline(provider()).run(_request(source))
    second = await _pipeline(provider()).run(_request(source))

    assert first.manifest.request_fingerprint == second.manifest.request_fingerprint
    assert first.manifest.artifact_id == second.manifest.artifact_id
