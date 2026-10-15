"""Requests can only confirm the exact server-bound record and listed choices."""

import pytest

from autoformat.feedback_contracts import (
    FeedbackConfirmationRequest, FeedbackDecisionRequest, FeedbackParseResult,
    SelectionAnchor, SelectionResolution,
)
from autoformat.feedback_store import FeedbackError
from autoformat.feedback_validation import (
    validate_confirmation, validate_conflict_decision, validate_parse_result,
    validate_selection_resolution,
)

from conftest import submission_for
from test_contracts import candidate, review, sealed


def record_and_result(feedback_env, **changes):
    _, feedback, _, v1, _ = feedback_env
    context = feedback.context(v1.task_id, v1.version_id)
    receipt = feedback.submit(v1.task_id, v1.version_id, submission_for(context))
    record = feedback.get(v1.task_id, v1.version_id, receipt.feedback_id)
    data = {"schema_version": "feedback-parse-result/1.0", "task_id": v1.task_id,
        "feedback_id": record.feedback_id, "version_context_id": context.context_id,
        "source_submission_sha256": record.source_submission_sha256,
        "parser_id": "deterministic", "parser_version": "1.0", "kind": "new_rule",
        "candidates": [candidate().model_dump(mode="json")], "reason": "测试类型化候选。"}
    data.update(changes)
    result = sealed(FeedbackParseResult, data, "result_id")
    return record, context, result


def request_fields(record, context, result):
    return {"request_id": "9" * 32, "task_id": context.task_id,
        "base_version_id": context.base_version_id, "expected_base_docx_sha256": context.base_docx_sha256,
        "expected_context_id": context.context_id, "feedback_id": record.feedback_id,
        "expected_parse_result_id": result.result_id}


def test_parse_result_binding_and_scope_control(feedback_env):
    record, context, result = record_and_result(feedback_env)
    validate_parse_result(record, context, result, known_rule_ids=set())
    changed = result.model_dump(mode="json", exclude={"result_id"})
    changed["source_submission_sha256"] = "f" * 64
    with pytest.raises(FeedbackError) as error:
        validate_parse_result(record, context, sealed(FeedbackParseResult, changed, "result_id"), known_rule_ids=set())
    assert error.value.status == "stale_base_version"
    changed["source_submission_sha256"] = record.source_submission_sha256
    changed["candidates"][0]["requested_scope"] = "document"
    with pytest.raises(FeedbackError) as error:
        validate_parse_result(record, context, sealed(FeedbackParseResult, changed, "result_id"), known_rule_ids=set())
    assert error.value.status == "needs_user_input"
    changed["kind"] = "clarification_needed"
    changed["missing_fields"] = ["requested_scope"]
    validate_parse_result(record, context, sealed(FeedbackParseResult, changed, "result_id"), known_rule_ids=set())


def test_execution_defect_cannot_reference_an_unknown_rule(feedback_env):
    record, context, result = record_and_result(feedback_env, kind="execution_defect",
        candidates=[], existing_rule_ids=["brief-rule-1"])
    with pytest.raises(FeedbackError) as error:
        validate_parse_result(record, context, result, known_rule_ids=set())
    assert error.value.status == "validation_failed"
    validate_parse_result(record, context, result, known_rule_ids={"brief-rule-1"})


def test_confirm_scope_matches_current_hash_and_review_ids(feedback_env):
    scope = review().model_dump(mode="json")
    record, context, result = record_and_result(feedback_env, scope_reviews=[scope])
    request = FeedbackConfirmationRequest(**request_fields(record, context, result),
        schema_version="feedback-confirmation-request/1.0",
        answer={"action": "confirm_scope", "accepted_review_ids": [scope["review_id"]]})
    validate_confirmation(record, context, result, request, known_rule_ids=set())
    for changes, status in (({"expected_parse_result_id": "f" * 64}, "stale_base_version"),
        ({"answer": {"action": "confirm_scope", "accepted_review_ids": ["f" * 64]}}, "needs_user_input")):
        data = request.model_dump(mode="json")
        data.update(changes)
        with pytest.raises(FeedbackError) as error:
            validate_confirmation(record, context, result, FeedbackConfirmationRequest.model_validate(data), known_rule_ids=set())
        assert error.value.status == status


def test_target_confirmation_only_accepts_current_listed_candidates(feedback_env):
    record, context, result = record_and_result(feedback_env)
    resolution = sealed(SelectionResolution, {"schema_version": "selection-resolution/1.0",
        "feedback_id": record.feedback_id, "version_context_id": context.context_id,
        "status": "ambiguous", "candidates": [{"candidate_id": "target-1", "object_id": "p:000001",
            "location_label": "第1段", "excerpt": "Selectable preview text"}], "reason": "需选择目标。"}, "resolution_id")
    request = FeedbackConfirmationRequest(**request_fields(record, context, result),
        schema_version="feedback-confirmation-request/1.0",
        answer={"action": "select_target", "expected_resolution_id": resolution.resolution_id,
                "selected_candidate_ids": ["target-1"]})
    validate_confirmation(record, context, result, request, known_rule_ids=set(), resolution=resolution)
    data = request.model_dump(mode="json")
    data["answer"]["selected_candidate_ids"] = ["unknown-target"]
    with pytest.raises(FeedbackError) as error:
        validate_confirmation(record, context, result, FeedbackConfirmationRequest.model_validate(data),
                              known_rule_ids=set(), resolution=resolution)
    assert error.value.status == "needs_user_input"
    data["answer"]["expected_resolution_id"] = "f" * 64
    with pytest.raises(FeedbackError) as error:
        validate_confirmation(record, context, result, FeedbackConfirmationRequest.model_validate(data),
                              known_rule_ids=set(), resolution=resolution)
    assert error.value.status == "stale_preview"


def test_ready_anchor_is_bound_to_exact_version_preview_and_selection(feedback_env):
    record, context, _ = record_and_result(feedback_env)
    data = {"schema_version": "selection-anchor/1.1", "task_id": context.task_id,
        "base_version_id": context.base_version_id, "base_docx_sha256": context.base_docx_sha256,
        "preview_artifact_id": context.preview_artifact_id, "preview_pdf_sha256": context.preview_pdf_sha256,
        "renderer_id": context.renderer_id, "renderer_version": context.renderer_version,
        "selection": record.submission.selection.model_dump(mode="json"),
        "ranges": [{"object_id": "p:000001", "start_utf16": 0, "length_utf16": 23,
                    "matched_text": "Selectable preview text"}], "status": "ready"}
    resolution_data = {"schema_version": "selection-resolution/1.0", "feedback_id": record.feedback_id,
        "version_context_id": context.context_id, "status": "ready",
        "anchor": sealed(SelectionAnchor, data, "anchor_id").model_dump(mode="json"), "reason": "唯一目标。"}
    validate_selection_resolution(record, context, sealed(SelectionResolution, resolution_data, "resolution_id"))
    for field, value in (("preview_artifact_id", "other-preview"), ("base_version_id", "f" * 32),
                         ("renderer_version", "other renderer"), ("preview_pdf_sha256", "f" * 64)):
        changed = {**data, field: value}
        resolution_data["anchor"] = sealed(SelectionAnchor, changed, "anchor_id").model_dump(mode="json")
        with pytest.raises(FeedbackError) as error:
            validate_selection_resolution(record, context, sealed(SelectionResolution, resolution_data, "resolution_id"))
        assert error.value.status == "stale_preview"


def test_clarification_preserves_understood_fields(feedback_env):
    record, context, result = record_and_result(feedback_env, kind="clarification_needed", candidates=[],
        understood=[{"candidate_id": "candidate-1", "property_id": "font.size", "requested_scope": "selection"}],
        missing_fields=["value"])
    request = FeedbackConfirmationRequest(**request_fields(record, context, result),
        schema_version="feedback-confirmation-request/1.0",
        answer={"action": "clarify_format", "format": candidate().model_dump(mode="json")})
    validate_confirmation(record, context, result, request, known_rule_ids=set())
    data = request.model_dump(mode="json")
    data["answer"]["format"] = candidate(property_id="font.family", value={"normalized": "宋体"}).model_dump(mode="json")
    with pytest.raises(FeedbackError) as error:
        validate_confirmation(record, context, result, FeedbackConfirmationRequest.model_validate(data), known_rule_ids=set())
    assert error.value.status == "needs_user_input"


def test_conflict_choice_keeps_local_exception_local(feedback_env):
    record, context, result = record_and_result(feedback_env, scope_reviews=[review().model_dump(mode="json")],
        conflicts=[{"conflict_id": "conflict-1", "candidate_id": "candidate-1", "existing_rule_ids": ["brief-rule-1"],
                    "property_id": "font.size", "affected_target_ids": ["p:000001"], "reason": "字号不同。"}])
    data = {**request_fields(record, context, result), "schema_version": "feedback-decision-request/1.0",
            "conflict_id": "conflict-1", "action": "local_exception"}
    validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    data["action"] = "keep_rule"
    validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    data["action"] = "update_rule"
    with pytest.raises(FeedbackError) as error:
        validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    assert error.value.status == "needs_user_input"


def test_global_rule_update_requires_displayed_global_scope(feedback_env):
    global_review = review(effective_scope="document", requires_confirmation=True).model_dump(mode="json")
    record, context, result = record_and_result(feedback_env, scope_reviews=[global_review],
        conflicts=[{"conflict_id": "conflict-1", "candidate_id": "candidate-1", "existing_rule_ids": ["brief-rule-1"],
                    "property_id": "font.size", "affected_target_ids": ["p:000001"], "reason": "字号不同。"}])
    data = {**request_fields(record, context, result), "schema_version": "feedback-decision-request/1.0",
            "conflict_id": "conflict-1", "action": "update_rule"}
    validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    data["action"] = "local_exception"
    with pytest.raises(FeedbackError) as error:
        validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    assert error.value.status == "needs_user_input"
    data["conflict_id"] = "unknown-conflict"
    with pytest.raises(FeedbackError) as error:
        validate_conflict_decision(record, context, result, FeedbackDecisionRequest.model_validate(data), known_rule_ids={"brief-rule-1"})
    assert error.value.status == "needs_user_input"
