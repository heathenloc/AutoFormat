from __future__ import annotations

from scripts.compile_domain_packs import DOMAIN_PACK_ROOT, build_loader

from brief_parser.adapters.fake_provider import FakeModelProvider
from brief_parser.application.output_compilation import OutputCompiler
from brief_parser.application.service import (
    BriefParserService,
    DomainPackCatalog,
    ParseServiceRequest,
    TextSourceInput,
)
from brief_parser.domain.candidates import ExtractorOutput
from brief_parser.domain.enums import ExecutionReadiness, ModelRole, Priority
from tests.e2e.test_pipeline import (
    _auditor,
    _duration_extractor,
    _foundation,
    _pipeline,
    _request,
    _source,
)


async def test_pipeline_ir_compiles_to_execution_brief_and_markdown() -> None:
    source = _source("成片时长不得超过60秒。", source_id="src_phase5")
    clause = _foundation(source).clauses[0]
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
            ModelRole.AUDITOR: [
                _auditor([clause.clause_id], [clause.evidence_id])
            ],
        }
    )
    pipeline_result = await _pipeline(provider).run(_request(source))
    pack = build_loader().load_yaml(
        DOMAIN_PACK_ROOT / "advertising_brief" / "1.0.0.yaml"
    )

    outputs = OutputCompiler().compile(
        pipeline_result.requirement_ir,
        pack,
        task_types=["write_ad_script"],
    )

    brief = outputs.execution_briefs["write_ad_script"]
    assert outputs.requirement_ir.artifact_id == pipeline_result.requirement_ir.artifact_id
    assert brief.readiness == ExecutionReadiness.READY
    assert brief.hard_constraints[0].source_requirement_id == (
        outputs.requirement_ir.requirements[0].id
    )
    assert clause.evidence_id in brief.hard_constraints[0].evidence_refs
    assert "## Execution Brief: write\\_ad\\_script" in outputs.result_markdown
    assert clause.raw_text in outputs.result_markdown


async def test_service_applies_reviewed_pack_risk_to_model_candidate() -> None:
    text = "成片时长不得超过60秒。"
    clause = _foundation(_source(text, source_id="src_001")).clauses[0]
    candidate = ExtractorOutput.model_validate(_duration_extractor(clause.evidence_id))
    lowered = candidate.model_copy(
        update={
            "requirements": [
                candidate.requirements[0].model_copy(
                    update={"priority": Priority.NORMAL}
                )
            ]
        }
    )
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [lowered],
            ModelRole.AUDITOR: [_auditor([clause.clause_id], [clause.evidence_id])],
        }
    )
    pack = build_loader().load_yaml(
        DOMAIN_PACK_ROOT / "advertising_brief" / "1.0.0.yaml"
    )
    service = BriefParserService(
        _pipeline(provider),
        DomainPackCatalog({(pack.id, pack.version): pack}),
    )

    bundle = await service.parse(
        ParseServiceRequest(
            request_id="req_pack_risk",
            domain_pack_id=pack.id,
            requested_task_types=("write_ad_script",),
            text_sources=(
                TextSourceInput(text=text, client_source_id="synthetic-brief"),
            ),
        )
    )

    assert bundle.requirement_ir.requirements[0].priority == Priority.HIGH
    assert bundle.requirement_ir.readiness == "complete"
