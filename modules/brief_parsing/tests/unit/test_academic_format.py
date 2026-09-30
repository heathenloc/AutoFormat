"""Academic projection admits only explicit, fully evidenced format rules."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from brief_parser.compilers.academic_format import AcademicFormatCompiler
from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.requirement_ir import RequirementIR
from scripts.compile_domain_packs import build_loader
from tests.factories import requirement_ir_payload


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT.parents[1] / "contracts" / "academic-format-rule-set" / (
    "academic-format-rule-set-1.0.schema.json"
)


def _academic_ir() -> RequirementIR:
    payload = requirement_ir_payload()
    quote = "正文段落应居中"
    payload["domain_pack"] = {"id": "academic_paper", "version": "1.0.0"}
    source = payload["source_manifest"][0]
    source["byte_size"] = len(quote.encode("utf-8"))
    source["sha256"] = sha256(quote.encode("utf-8")).hexdigest()
    requirement = payload["requirements"][0]
    requirement.update({
        "id": "req_body_alignment", "semantic_key": "body.paragraph.alignment",
        "category": "body_text", "label": "正文段落居中", "subject": "body",
        "operator": "eq", "modality": "must",
        "value": {"type": "paragraph_alignment", "amount": "center", "unit": None},
        "scope": {"applies_to": ["body"], "excludes": []},
        "priority": "high", "downstream_policy": "enforce",
    })
    evidence = payload["evidence_index"]["ev_duration"]
    evidence.update({
        "quote": quote, "quote_sha256": sha256(quote.encode("utf-8")).hexdigest(),
        "end": len(quote), "match_status": "exact",
    })
    return RequirementIR.model_validate(payload)


def _compile(ir: RequirementIR, explicit: tuple[str, ...] = ("req_body_alignment",)) -> AcademicFormatRuleSet:
    pack = build_loader().load_json(
        ROOT / "domain_packs" / "academic_paper" / "1.0.0.json"
    )
    return AcademicFormatCompiler().compile(
        ir, pack, explicit_requirement_ids=explicit
    )


def test_exact_explicit_body_alignment_has_versioned_evidence() -> None:
    ruleset = _compile(_academic_ir())
    assert ruleset.issues == [] and len(ruleset.rules) == 1
    rule = ruleset.rules[0]
    assert rule.status == "verified"
    assert rule.source_kind == "brief_explicit"
    assert rule.source_version == "art_sample:v1"
    assert rule.target.semantic_role == "body"
    assert rule.target.selector == "semantic_role"
    assert rule.property_id == "paragraph.alignment"
    assert rule.value.original_text == "居中"
    assert rule.value.normalized == "center"
    assert rule.requested_scope == "same_kind"
    assert rule.evidence_refs[0].quote == "正文段落应居中"
    Draft202012Validator(json.loads(CONTRACT.read_text(encoding="utf-8"))).validate(
        ruleset.model_dump(mode="json")
    )


def test_unclassified_or_nonexact_evidence_never_creates_rule() -> None:
    ir = _academic_ir()
    unclassified = _compile(ir, ())
    assert unclassified.rules == []
    assert unclassified.issues[0].status == "needs_source_classification"
    nonexact_payload = ir.model_dump(mode="python")
    nonexact_payload["evidence_index"]["ev_duration"]["match_status"] = "normalized"
    nonexact = _compile(RequirementIR.model_validate(nonexact_payload))
    assert nonexact.rules == []
    assert nonexact.issues[0].status == "evidence_unverified"


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("正文不得居中", "value_evidence_mismatch"),
        ("正文左对齐或居中", "value_evidence_mismatch"),
        ("正文统一右对齐", "value_evidence_mismatch"),
    ],
)
def test_mismatched_or_negated_words_pause(quote: str, expected: str) -> None:
    payload = _academic_ir().model_dump(mode="python")
    evidence = payload["evidence_index"]["ev_duration"]
    evidence["quote"] = quote
    evidence["quote_sha256"] = sha256(quote.encode("utf-8")).hexdigest()
    evidence["end"] = len(quote)
    result = _compile(RequirementIR.model_validate(payload))
    assert result.rules == [] and result.issues[0].status == expected


def test_condition_scope_and_conflict_remain_unexecuted() -> None:
    ir = _academic_ir()
    condition_payload = ir.model_dump(mode="python")
    condition_payload["requirements"][0]["condition"] = {
        "expression": "print submission", "evidence_refs": ["ev_duration"],
    }
    assert _compile(RequirementIR.model_validate(condition_payload)).issues[0].status == (
        "pending_condition"
    )

    scope_payload = ir.model_dump(mode="python")
    scope_payload["requirements"][0]["scope"]["applies_to"] = ["body", "heading"]
    assert _compile(RequirementIR.model_validate(scope_payload)).issues[0].status == (
        "unsupported"
    )

    conflict_payload = ir.model_dump(mode="python")
    second = deepcopy(conflict_payload["requirements"][0])
    second["id"] = "req_competing"
    conflict_payload["requirements"].append(second)
    conflict_payload["conflicts"] = [{
        "id": "conflict_alignment", "topic": "body.alignment", "severity": "blocker",
        "items": ["req_body_alignment", "req_competing"],
        "reason_code": "different_values", "resolution": None,
        "downstream_policy": "block",
    }]
    conflicted = _compile(
        RequirementIR.model_validate(conflict_payload),
        ("req_body_alignment", "req_competing"),
    )
    assert conflicted.rules == []
    assert {issue.status for issue in conflicted.issues} == {"pending_conflict"}


def test_incomplete_ir_and_unknown_property_are_reported() -> None:
    payload = _academic_ir().model_dump(mode="python")
    payload["readiness"] = "incomplete"
    assert _compile(RequirementIR.model_validate(payload)).issues[0].status == (
        "parse_incomplete"
    )
    payload["readiness"] = "complete"
    payload["requirements"][0]["value"]["type"] = "font_family"
    assert _compile(RequirementIR.model_validate(payload)).issues[0].status == (
        "unsupported"
    )


def test_schema_snapshot_matches_strict_model() -> None:
    expected = AcademicFormatRuleSet.model_json_schema()
    expected["$id"] = "https://easyformat.local/contracts/academic-format-rule-set/1.0"
    assert json.loads(CONTRACT.read_text(encoding="utf-8")) == expected
