"""Contract shape, semantic safety, provenance and historical schema checks."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from autoformat.feedback_contracts import (
    CONTRACTS, DocxTextRange, FeedbackConfirmationRequest, FeedbackDecisionRequest,
    FeedbackEffectiveRule, FeedbackParseResult, FeedbackRuleCandidate, FeedbackRuleSnapshot,
    FeedbackSubmission, FeedbackVersionContext, PdfTextSpan, ScopeReview,
    SelectionAnchor, SelectionHint, SelectionResolution, contract_schema, seal_contract,
)

ROOT = Path(__file__).resolve().parents[2]


def sealed(model, payload, field):
    return seal_contract(model, payload, field)


def anchor():
    return sealed(SelectionAnchor, {
        "schema_version": "selection-anchor/1.1", "task_id": "1" * 32,
        "base_version_id": "2" * 32, "base_docx_sha256": "3" * 64,
        "preview_artifact_id": "preview-1", "preview_pdf_sha256": "4" * 64,
        "renderer_id": "libreoffice", "renderer_version": "LibreOffice 26.8.0.3",
        "selection": SelectionHint(selected_text="字😀", spans=[PdfTextSpan(page=1,
            start_item=0, start_offset_utf16=0, end_item=0, end_offset_utf16=3)]).model_dump(mode="json"),
        "ranges": [DocxTextRange(object_id="p:000001", start_utf16=0,
            length_utf16=3, matched_text="字😀").model_dump(mode="json")], "status": "ready",
    }, "anchor_id")


def candidate(**changes):
    payload = {"candidate_id": "candidate-1", "property_id": "font.size",
               "value": {"normalized": 15, "unit": "pt"}, "requested_scope": "selection"}
    payload.update(changes)
    return FeedbackRuleCandidate.model_validate(payload)


def review(**changes):
    payload = {"candidate_id": "candidate-1", "requested_scope": "selection",
        "effective_scope": "selection", "minimum_unit": "character", "target_ids": ["p:000001"],
        "estimated_affected_count": 1, "requires_confirmation": False, "reason": "仅选中字符。"}
    payload.update(changes)
    return sealed(ScopeReview, payload, "review_id")


def parsed(**changes):
    payload = {"schema_version": "feedback-parse-result/1.0", "task_id": "1" * 32,
        "feedback_id": "5" * 32, "version_context_id": "6" * 64,
        "source_submission_sha256": "7" * 64, "parser_id": "deterministic",
        "parser_version": "1.0", "kind": "new_rule",
        "candidates": [candidate().model_dump(mode="json")], "reason": "已理解字号要求；尚未获得执行许可。"}
    payload.update(changes)
    return sealed(FeedbackParseResult, payload, "result_id")


def rule(**changes):
    payload = {"rule_id": "feedback-rule-1", "feedback_id": "5" * 32,
        "source_submission_sha256": "7" * 64, "parse_result_id": parsed().result_id,
        "origin_version_id": "2" * 32, "candidate": candidate(), "scope_review": review(),
        "anchor": anchor(), "effect": "new_rule", "status": "verified"}
    payload.update(changes)
    return FeedbackEffectiveRule(**payload)


def request_base():
    return {"request_id": "8" * 32, "task_id": "1" * 32, "base_version_id": "2" * 32,
            "expected_base_docx_sha256": "3" * 64, "expected_context_id": "6" * 64,
            "feedback_id": "5" * 32, "expected_parse_result_id": parsed().result_id}


def test_exported_contracts_are_standalone_and_match_both_copies():
    from autoformat.feedback_rules_contracts import RULE_CONTRACTS
    from autoformat.feedback_execution_contracts import EXECUTION_CONTRACTS
    from autoformat.workspace_contracts import WORKSPACE_CONTRACTS
    for version, model in (CONTRACTS | RULE_CONTRACTS | EXECUTION_CONTRACTS | WORKSPACE_CONTRACTS).items():
        kind, number = version.split("/")
        expected = contract_schema(model)
        Draft202012Validator.check_schema(expected)
        paths = [ROOT / "contracts" / kind / f"{kind}-{number}.schema.json",
                 ROOT / "apps/api/src/autoformat/schemas" / f"{kind}-{number}.schema.json"]
        assert all(json.loads(path.read_text(encoding="utf-8")) == expected for path in paths)
        assert expected["additionalProperties"] is False
        assert "schema_version" in expected["required"]
    old = json.loads((ROOT / "contracts/selection-anchor/selection-anchor-1.0.schema.json").read_text(encoding="utf-8"))
    assert old["properties"]["schema_version"]["const"] == "selection-anchor/1.0"
    assert "docx_xml_path" in old["properties"]


def test_example_request_is_valid_and_bound_to_example_context():
    context_data = json.loads((ROOT / "contracts/feedback-version-context/example.json").read_text(encoding="utf-8"))
    request_data = json.loads((ROOT / "contracts/feedback-submission/example-selection.json").read_text(encoding="utf-8"))
    for model, payload in ((FeedbackVersionContext, context_data), (FeedbackSubmission, request_data)):
        Draft202012Validator(contract_schema(model)).validate(payload)
    context = FeedbackVersionContext.model_validate(context_data)
    request = FeedbackSubmission.model_validate(request_data)
    assert request.expected_context_id == context.context_id
    assert request.expected_base_docx_sha256 == context.base_docx_sha256
    assert request.expected_preview_pdf_sha256 == context.preview_pdf_sha256


@pytest.mark.parametrize("prop,value,unit", [
    ("unknown.property", 10, "pt"), ("font.size", True, "pt"), ("font.size", -1, "pt"),
    ("font.size", 15, "cm"), ("font.size", float("inf"), "pt"),
    ("font.bold", "yes", None), ("paragraph.alignment", "middle", None),
    ("page_number.start", 1.5, None), ("font.family", "A\nB", None),
])
def test_candidates_require_registered_typed_values(prop, value, unit):
    with pytest.raises(ValidationError):
        candidate(property_id=prop, value={"normalized": value, "unit": unit})


def test_common_values_validate_without_parsing_user_prose():
    assert candidate().value.normalized == 15
    assert candidate(property_id="font.bold", value={"normalized": True}).value.normalized is True
    assert candidate(property_id="paragraph.line_spacing", value={"normalized": {"mode": "exact", "amount": 20}, "unit": "pt"})
    with pytest.raises(ValidationError):
        candidate(requested_scope="same_kind")
    with pytest.raises(ValidationError):
        candidate(semantic_role="invented_role")
    with pytest.raises(ValidationError):
        candidate(applicability_scope={"axes": {"unregistered_axis": {"include": ["1"], "exclude": []}}})
    with pytest.raises(ValidationError):
        candidate(property_id="font.family", value={"normalized": "\ud800"})


def test_character_offsets_use_utf16_and_preserve_exact_text():
    resolved = anchor()
    assert resolved.ranges[0].length_utf16 == 3
    assert resolved.selection.selected_text == "字😀"
    Draft202012Validator(contract_schema(SelectionAnchor)).validate(resolved.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        DocxTextRange(object_id="p:000001", start_utf16=0, length_utf16=2, matched_text="字😀")
    with pytest.raises(ValidationError):
        PdfTextSpan(page=True, start_item=0, start_offset_utf16=0, end_item=0, end_offset_utf16=1)
    with pytest.raises(ValidationError):
        SelectionHint(selected_text="a", spans=[PdfTextSpan(page=2, start_item=0, start_offset_utf16=0, end_item=0, end_offset_utf16=1),
            PdfTextSpan(page=1, start_item=0, start_offset_utf16=0, end_item=0, end_offset_utf16=1)])


def test_scope_cannot_hide_expansion_or_lie_about_word_unit():
    assert review(effective_scope="paragraph", minimum_unit="paragraph").effective_scope == "paragraph"
    with pytest.raises(ValidationError):
        review(effective_scope="document")
    with pytest.raises(ValidationError):
        review(minimum_unit="paragraph")
    with pytest.raises(ValidationError):
        review(target_ids=["p:000001", "p:000001"], estimated_affected_count=2)
    with pytest.raises(ValidationError):
        review(estimated_affected_count=2)
    with pytest.raises(ValidationError):
        parsed(candidates=[candidate(property_id="paragraph.alignment", value={"normalized": "center"}).model_dump(mode="json")],
               scope_reviews=[review().model_dump(mode="json")])


@pytest.mark.parametrize("changes", [
    {"kind": "execution_defect"}, {"kind": "question"}, {"kind": "out_of_scope"},
    {"kind": "clarification_needed"}, {"kind": "new_rule", "candidates": []},
    {"conflicts": [{"conflict_id": "c", "candidate_id": "missing", "existing_rule_ids": ["r"],
                     "property_id": "font.size", "affected_target_ids": ["p:000001"], "reason": "冲突"}]},
])
def test_feedback_classification_does_not_invent_execution_rules(changes):
    with pytest.raises(ValidationError):
        parsed(**changes)


def test_execution_defect_references_existing_rule_and_hashes_are_checked():
    result = parsed(kind="execution_defect", candidates=[], existing_rule_ids=["brief-rule-1"])
    assert not result.candidates
    data = result.model_dump(mode="json")
    data["existing_rule_ids"] = ["changed"]
    with pytest.raises(ValidationError):
        FeedbackParseResult.model_validate(data)


def test_confirmation_and_conflict_requests_only_accept_typed_choices():
    confirmation = FeedbackConfirmationRequest(**request_base(), schema_version="feedback-confirmation-request/1.0",
        answer={"action": "confirm_scope", "accepted_review_ids": [review().review_id]})
    decision = FeedbackDecisionRequest(**request_base(), schema_version="feedback-decision-request/1.0",
        conflict_id="conflict-1", action="local_exception")
    for model, value in ((FeedbackConfirmationRequest, confirmation), (FeedbackDecisionRequest, decision)):
        payload = value.model_dump(mode="json")
        Draft202012Validator(contract_schema(model)).validate(payload)
        payload["rules"] = [{"status": "verified"}]
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    with pytest.raises(ValidationError):
        FeedbackConfirmationRequest(**request_base(), schema_version="feedback-confirmation-request/1.0",
            answer={"action": "confirm_scope", "accepted_review_ids": [review().review_id], "selected_candidate_ids": ["extra"]})


def test_snapshot_requires_exception_decision_and_origin_anchor():
    with pytest.raises(ValidationError):
        rule(effect="local_exception")
    with pytest.raises(ValidationError):
        rule(origin_version_id="9" * 32)
    with pytest.raises(ValidationError):
        rule(anchor=None)
    with pytest.raises(ValidationError):
        rule(scope_review=review(target_ids=["p:000002"]))
    confirmed = rule(effect="local_exception", decision_id="a" * 32)
    payload = {"schema_version": "feedback-rule-snapshot/1.0", "compiler_version": "feedback-rules/1.0",
        "parent_snapshot_id": None, "task_id": "1" * 32, "base_version_id": "2" * 32,
        "base_docx_sha256": "3" * 64, "brief_version_id": "brief:v1", "academic_rules_snapshot_id": "rules-1",
        "rules": [confirmed.model_dump(mode="json")], "decision_ids": ["a" * 32]}
    snapshot = sealed(FeedbackRuleSnapshot, payload, "snapshot_id")
    Draft202012Validator(contract_schema(FeedbackRuleSnapshot)).validate(snapshot.model_dump(mode="json"))
    payload["decision_ids"] = []
    with pytest.raises(ValidationError):
        sealed(FeedbackRuleSnapshot, payload, "snapshot_id")


def test_ambiguous_resolution_never_exposes_a_ready_anchor():
    payload = {"schema_version": "selection-resolution/1.0", "feedback_id": "5" * 32,
        "version_context_id": "6" * 64, "status": "ambiguous", "reason": "重复文字需要选择目标。"}
    assert sealed(SelectionResolution, payload, "resolution_id").anchor is None
    payload["anchor"] = anchor().model_dump(mode="json")
    with pytest.raises(ValidationError):
        sealed(SelectionResolution, payload, "resolution_id")


def test_child_snapshot_requires_fresh_anchor_and_keeps_exception_origin():
    original_rule = rule(effect="local_exception", decision_id="a" * 32)
    payload = {"schema_version": "feedback-rule-snapshot/1.0", "compiler_version": "feedback-rules/1.0",
        "parent_snapshot_id": None, "task_id": "1" * 32, "base_version_id": "2" * 32,
        "base_docx_sha256": "3" * 64, "brief_version_id": "brief:v1", "academic_rules_snapshot_id": "rules-1",
        "rules": [original_rule.model_dump(mode="json")], "decision_ids": ["a" * 32]}
    first = sealed(FeedbackRuleSnapshot, payload, "snapshot_id")
    payload.update(parent_snapshot_id=first.snapshot_id, base_version_id="b" * 32, base_docx_sha256="c" * 64)
    with pytest.raises(ValidationError):
        sealed(FeedbackRuleSnapshot, payload, "snapshot_id")
    # Unresolved inheritance is representable, but not marked verified.
    payload["rules"] = [rule(effect="local_exception", decision_id="a" * 32,
                             status="pending_target").model_dump(mode="json")]
    assert sealed(FeedbackRuleSnapshot, payload, "snapshot_id").rules[0].status == "pending_target"
    remap_data = anchor().model_dump(mode="json", exclude={"anchor_id"})
    remap_data.update(base_version_id="b" * 32, base_docx_sha256="c" * 64)
    remap_data["ranges"][0]["object_id"] = "p:000007"
    remapped = sealed(SelectionAnchor, remap_data, "anchor_id")
    payload["rules"] = [rule(effect="local_exception", decision_id="a" * 32,
        resolved_anchor=remapped, scope_review=review(target_ids=["p:000007"])).model_dump(mode="json")]
    child = sealed(FeedbackRuleSnapshot, payload, "snapshot_id")
    assert child.rules[0].origin_version_id == first.rules[0].origin_version_id
    assert child.rules[0].anchor == first.rules[0].anchor
    assert child.rules[0].resolved_anchor.base_version_id == child.base_version_id
