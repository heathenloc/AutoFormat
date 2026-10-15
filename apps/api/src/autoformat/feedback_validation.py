"""Cross-record gates for later server-side adapters, never edit authorization.

Callers load the record/context/reviews from trusted storage and derive known
rule IDs from a source-replayed snapshot. Matching IDs is necessary but does
not replace actual PDF/DOCX resolution, conflict analysis or source replay.
"""

from .feedback_contracts import (
    FeedbackConfirmationRequest, FeedbackDecisionRequest, FeedbackParseResult,
    FeedbackRecord, FeedbackVersionContext, SelectionResolution,
)
from .feedback_store import FeedbackError, FeedbackStore


def _checked(value):
    try:
        return type(value).model_validate_json(value.model_dump_json())
    except ValueError as error:
        raise FeedbackError("validation_failed", "反馈处理记录无法通过契约校验。") from error


def validate_parse_result(record: FeedbackRecord, context: FeedbackVersionContext,
                          result: FeedbackParseResult, *, known_rule_ids: set[str]) -> None:
    record, context, result = map(_checked, (record, context, result))
    FeedbackStore._check_binding(record.submission, context)
    if (result.task_id != context.task_id or result.feedback_id != record.feedback_id
            or result.version_context_id != context.context_id
            or result.source_submission_sha256 != record.source_submission_sha256):
        raise FeedbackError("stale_base_version", "解析结果不属于此反馈或所选版本。")
    referred = set(result.existing_rule_ids)
    referred.update(rule for conflict in result.conflicts for rule in conflict.existing_rule_ids)
    if not referred <= known_rule_ids:
        raise FeedbackError("validation_failed", "解析结果引用了当前依据中不存在的规则。")
    if any(candidate.requested_scope != record.submission.requested_scope for candidate in result.candidates):
        if result.kind != "clarification_needed" or "requested_scope" not in result.missing_fields:
            raise FeedbackError("needs_user_input", "输入表达与范围控件不同，需先统一作用范围。")


def validate_selection_resolution(record: FeedbackRecord, context: FeedbackVersionContext,
                                  resolution: SelectionResolution) -> None:
    record, context, resolution = map(_checked, (record, context, resolution))
    FeedbackStore._check_binding(record.submission, context)
    if resolution.feedback_id != record.feedback_id or resolution.version_context_id != context.context_id:
        raise FeedbackError("stale_preview", "定位结果不属于此反馈预览。")
    anchor = resolution.anchor
    if anchor is not None:
        if (anchor.task_id != context.task_id or anchor.base_version_id != context.base_version_id
                or anchor.base_docx_sha256 != context.base_docx_sha256
                or anchor.preview_artifact_id != context.preview_artifact_id
                or anchor.preview_pdf_sha256 != context.preview_pdf_sha256
                or anchor.renderer_id != context.renderer_id or anchor.renderer_version != context.renderer_version
                or anchor.selection != record.submission.selection):
            raise FeedbackError("stale_preview", "语义锚点不属于原反馈的版本与选区。")


def _request_binding(record, context, result, request, known_rule_ids):
    validate_parse_result(record, context, result, known_rule_ids=known_rule_ids)
    if (request.task_id != context.task_id or request.base_version_id != context.base_version_id
            or request.expected_base_docx_sha256 != context.base_docx_sha256
            or request.expected_context_id != context.context_id
            or request.feedback_id != record.feedback_id or request.expected_parse_result_id != result.result_id):
        raise FeedbackError("stale_base_version", "用户决定所依据的反馈结果已变化。")


def validate_confirmation(record: FeedbackRecord, context: FeedbackVersionContext,
                          result: FeedbackParseResult, request: FeedbackConfirmationRequest, *,
                          known_rule_ids: set[str], resolution: SelectionResolution | None = None) -> None:
    record, context, result, request = map(_checked, (record, context, result, request))
    _request_binding(record, context, result, request, known_rule_ids)
    answer = request.answer
    if answer.action == "select_target":
        if resolution is None:
            raise FeedbackError("needs_user_input", "先取得明确的目标候选，再选择位置。")
        resolution = _checked(resolution)
        validate_selection_resolution(record, context, resolution)
        if answer.expected_resolution_id != resolution.resolution_id:
            raise FeedbackError("stale_preview", "目标候选已变化，请重新定位。")
        if resolution.status != "ambiguous" or not set(answer.selected_candidate_ids) <= {item.candidate_id for item in resolution.candidates}:
            raise FeedbackError("needs_user_input", "只能选择当前展示的目标候选。")
    elif answer.action == "confirm_scope":
        if not set(answer.accepted_review_ids) <= {review.review_id for review in result.scope_reviews}:
            raise FeedbackError("needs_user_input", "只能确认当前展示的实际作用范围。")
    else:
        if result.kind != "clarification_needed":
            raise FeedbackError("needs_user_input", "当前反馈不需要补充格式字段。")
        prior = next((item for item in [*result.candidates, *result.understood]
                      if item.candidate_id == answer.format.candidate_id), None)
        if prior is None:
            raise FeedbackError("needs_user_input", "补充答案需要绑定已展示的格式候选。")
        for field in ("property_id", "value", "semantic_role", "requested_scope", "character_scope", "applicability_scope"):
            before = getattr(prior, field, None)
            if before is not None and field not in result.missing_fields and before != getattr(answer.format, field):
                raise FeedbackError("needs_user_input", "补充答案不能改写已确定的格式字段。")


def validate_conflict_decision(record: FeedbackRecord, context: FeedbackVersionContext,
                              result: FeedbackParseResult, request: FeedbackDecisionRequest, *,
                              known_rule_ids: set[str]) -> None:
    record, context, result, request = map(_checked, (record, context, result, request))
    _request_binding(record, context, result, request, known_rule_ids)
    conflict = next((item for item in result.conflicts if item.conflict_id == request.conflict_id), None)
    if conflict is None:
        raise FeedbackError("needs_user_input", "只能决定当前展示的冲突。")
    if request.action == "keep_rule":
        return
    review = next((item for item in result.scope_reviews if item.candidate_id == conflict.candidate_id), None)
    if review is None:
        raise FeedbackError("needs_user_input", "先核对候选的实际作用范围。")
    allowed = {"selection", "paragraph"} if request.action == "local_exception" else {"same_kind", "document"}
    if review.effective_scope not in allowed:
        raise FeedbackError("needs_user_input", "此决定与展示的实际作用范围不同，需重新确认。")
