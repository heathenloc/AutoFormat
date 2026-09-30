"""Synthetic Phase 6 result builders."""

from __future__ import annotations

from dataclasses import replace

from scripts.compile_domain_packs import DOMAIN_PACK_ROOT, build_loader

from brief_parser.adapters.fake_provider import FakeModelProvider
from brief_parser.application.bundle import build_parse_bundle
from brief_parser.application.output_compilation import OutputCompiler
from brief_parser.domain.bundle import ParseBundle
from brief_parser.domain.enums import ModelRole
from tests.e2e.test_pipeline import (
    _auditor,
    _duration_extractor,
    _foundation,
    _pipeline,
    _request,
    _source,
)


async def make_parse_bundle() -> ParseBundle:
    source = _source("成片时长不得超过60秒。", source_id="src_phase6")
    clause = _foundation(source).clauses[0]
    provider = FakeModelProvider(
        {
            ModelRole.EXTRACTOR: [_duration_extractor(clause.evidence_id)],
            ModelRole.AUDITOR: [_auditor([clause.clause_id], [clause.evidence_id])],
        }
    )
    pipeline_result = await _pipeline(provider).run(
        replace(_request(source), requested_task_types=("write_ad_script",))
    )
    pack = build_loader().load_yaml(DOMAIN_PACK_ROOT / "advertising_brief" / "1.0.0.yaml")
    outputs = OutputCompiler().compile(
        pipeline_result.requirement_ir,
        pack,
        task_types=["write_ad_script"],
    )
    return build_parse_bundle(pipeline_result, outputs)
