"""Academic Brief facts reach a typed projection without an ExecutionBrief."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from brief_parser.adapters.fake_provider import FakeModelProvider
from brief_parser.application.service import (
    BriefParserService,
    DomainPackCatalog,
    ParseServiceRequest,
    TextSourceInput,
)
from brief_parser.compilers.academic_format import AcademicFormatCompiler
from brief_parser.compilers.academic_common_v1_1 import (
    AcademicCommonFormatExtractor as LegacyAcademicCommonFormatExtractor,
)
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from scripts.compile_domain_packs import DOMAIN_PACK_ROOT, build_loader
from tests.e2e.test_pipeline import (
    _auditor,
    _duration_extractor,
    _foundation,
    _pipeline,
    _source,
)


ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / "contracts" / "academic-parse-bundle" / (
    "academic-parse-bundle-1.2.schema.json"
)


def _service(text: str) -> BriefParserService:
    source = _source(text, source_id="src_001")
    clause = _foundation(source).clauses[0]
    candidate = _duration_extractor(clause.evidence_id)
    candidate["requirements"][0].update({
        "semantic_key": "body.paragraph.alignment",
        "category": "body_text", "label": "正文段落居中", "subject": "body",
        "operator": "eq", "priority": "high",
        "value": {
            "type": "paragraph_alignment", "text": "居中", "amount": None,
            "range_end": None, "unit": None, "items": [],
        },
        "scope": {"applies_to": ["body"], "excludes": []},
    })
    provider = FakeModelProvider({
        ModelRole.EXTRACTOR: [candidate],
        ModelRole.AUDITOR: [_auditor([clause.clause_id], [clause.evidence_id])],
    })
    pack = build_loader().load_yaml(
        DOMAIN_PACK_ROOT / "academic_paper" / "1.0.0.yaml"
    )
    return BriefParserService(
        _pipeline(provider), DomainPackCatalog({(pack.id, pack.version): pack})
    )


async def test_parse_only_bundle_then_academic_ruleset() -> None:
    text = "正文段落必须居中。"
    service = _service(text)
    request = ParseServiceRequest(
        request_id="req_academic_parse", domain_pack_id="academic_paper",
        requested_task_types=("format_academic_paper",),
        text_sources=(TextSourceInput(text=text, client_source_id="school-brief"),),
    )
    bundle = await service.parse_academic(request)
    assert bundle.bundle_version == "academic-parse-bundle/1.2"
    assert bundle.format_ruleset is not None
    assert len(bundle.format_ruleset.rules) == 1
    assert bundle.format_ruleset.rules[0].property_id == "paragraph.alignment"
    assert bundle.format_ruleset.rules[0].value.normalized == "center"
    assert bundle.manifest.requested_task_types == ["format_academic_paper"]
    assert bundle.requirement_ir.domain_pack.id == "academic_paper"
    assert bundle.requirement_ir.evidence_index
    assert "Execution Brief" not in bundle.renderings.markdown
    assert not hasattr(bundle, "execution_briefs")
    assert AcademicParseBundle.model_validate_json(bundle.model_dump_json()) == bundle
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(
        bundle.model_dump(mode="json")
    )

    pack = build_loader().load_yaml(
        DOMAIN_PACK_ROOT / "academic_paper" / "1.0.0.yaml"
    )
    requirement = bundle.requirement_ir.requirements[0]
    unclassified = AcademicFormatCompiler().compile_bundle(
        bundle, pack, explicit_requirement_ids=(),
    )
    assert unclassified.rules == []
    assert unclassified.issues[0].status == "needs_source_classification"
    classified = AcademicFormatCompiler().compile_bundle(
        bundle, pack, explicit_requirement_ids=(requirement.id,),
    )
    assert len(classified.rules) == 1
    assert classified.rules[0].value.normalized == "center"
    assert classified.rules[0].evidence_refs[0].quote == text

    changed_source = bundle.model_dump(mode="python")
    changed_source["manifest"]["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="sources differ"):
        AcademicParseBundle.model_validate(changed_source)

    changed_rule = bundle.model_dump(mode="python")
    changed_rule["format_ruleset"]["rules"][0]["value"]["normalized"] = "right"
    with pytest.raises(ValidationError, match="differs from source evidence"):
        AcademicParseBundle.model_validate(changed_rule)

    previous = bundle.model_dump(mode="python")
    previous["bundle_version"] = "academic-parse-bundle/1.1"
    previous["format_ruleset"] = LegacyAcademicCommonFormatExtractor().extract(
        bundle.requirement_ir
    ).model_dump(mode="python")
    assert AcademicParseBundle.model_validate(previous).bundle_version == (
        "academic-parse-bundle/1.1"
    )
    legacy_schema = json.loads(SCHEMA.with_name(
        "academic-parse-bundle-1.1.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(legacy_schema).validate(
        AcademicParseBundle.model_validate(previous).model_dump(mode="json")
    )

    historical = bundle.model_dump(mode="python")
    historical["bundle_version"] = "academic-parse-bundle/1.0"
    historical.pop("format_ruleset")
    assert AcademicParseBundle.model_validate(historical).format_ruleset is None


async def test_academic_parse_rejects_wrong_task_marker_before_pipeline() -> None:
    service = _service("正文段落必须居中。")
    with pytest.raises(BriefParserError) as error:
        await service.parse_academic(ParseServiceRequest(
            request_id="req_wrong_marker", domain_pack_id="academic_paper",
            requested_task_types=("write_ad_script",),
            text_sources=(TextSourceInput(text="正文段落必须居中。"),),
        ))
    assert error.value.code == ErrorCode.INVALID_REQUEST


def test_schema_snapshot_matches_model() -> None:
    expected = AcademicParseBundle.model_json_schema()
    expected["$id"] = "https://easyformat.local/contracts/academic-parse-bundle/1.2"
    expected["properties"]["bundle_version"].pop("enum")
    expected["properties"]["bundle_version"]["const"] = "academic-parse-bundle/1.2"
    nested = expected["$defs"]["AcademicFormatRuleSet"]["properties"]["schema_version"]
    nested.pop("enum")
    nested["const"] = "academic-format-rule-set/1.2"
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == expected
