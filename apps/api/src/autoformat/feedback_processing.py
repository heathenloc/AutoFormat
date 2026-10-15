"""Source-replayed feedback interpretation and append-only typed decisions.

This stage produces evidence, never an effective rule or an edit plan.
"""
from __future__ import annotations

from copy import deepcopy
import threading

from brief_parser.compilers.academic_scope import CHARACTERS

from .feedback_contracts import (FeedbackAnalysis, FeedbackConfirmationRequest, FeedbackDraftReview,
    FeedbackParseResult, FeedbackSubmission, canonical_bytes, content_hash, seal_contract)
from .feedback_parser import Interpretation, PARSER_ID, PARSER_VERSION, interpret
from .feedback_scope import build_scopes
from .feedback_store import FeedbackError, FeedbackStore
from .feedback_validation import validate_confirmation, validate_parse_result
from .selection_resolver import find_matches, verify_hint
from .selection_store import SelectionStore
from .version_store import _utc_now, new_id


class FeedbackProcessor:
    def __init__(self, feedback: FeedbackStore, indexes=None, *, selections=None, rule_loader=None):
        self.feedback, self.versions, self.indexes = feedback, feedback.versions, indexes
        self.selections = selections or SelectionStore(feedback, indexes)
        self.rule_loader = rule_loader or (lambda _: [])
        self._lock = threading.RLock()
        self.fingerprint = content_hash({"parser": PARSER_ID, "version": PARSER_VERSION,
            "indexes": indexes.fingerprint if indexes else None})
        with self.versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_parse_results (
                feedback_id TEXT NOT NULL REFERENCES feedback_submissions(feedback_id),
                result_id TEXT NOT NULL, engine_fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(feedback_id, result_id, engine_fingerprint))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_processing_decisions (
                decision_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, feedback_id TEXT NOT NULL,
                request_id TEXT NOT NULL, sequence INTEGER NOT NULL, action TEXT NOT NULL,
                source_result_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(task_id, request_id), UNIQUE(feedback_id, sequence))""")

    def _indexes(self, context):
        if self.indexes is None: return None, None
        path = self.versions.artifact_path(context.task_id, context.base_version_id, "docx")
        text, semantic = self.indexes.docx(path), self.indexes.semantic(path)
        if text.sha256 != context.base_docx_sha256 or semantic.sha256 != context.base_docx_sha256:
            raise FeedbackError("stale_base_version", "范围索引不属于所选 DOCX。")
        if len({o.object_id for o in semantic.objects}) != len(semantic.objects):
            raise FeedbackError("validation_failed", "范围索引重复对象身份。")
        return text, semantic

    @staticmethod
    def _role(selected_ids, semantic):
        roles = {o.semantic_role for o in semantic.objects if o.object_id in (selected_ids or [])} if semantic else set()
        return next(iter(roles)) if len(roles) == 1 and "unclassified" not in roles else None

    @staticmethod
    def _selected_texts(ranges):
        result = {}
        for span in ranges:
            result[span.object_id] = result.get(span.object_id, "") + span.matched_text
        return result

    def _facts(self, submission, source_hash, context, text, semantic, selected_ids):
        facts = interpret(submission.raw_text, submission.requested_scope, source_hash,
            selected_role=self._role(selected_ids, semantic))
        known = self.rule_loader(context) if facts.defect_properties else []
        if facts.defect_properties:
            roles = {o.semantic_role for o in semantic.objects if o.object_id in (selected_ids or [])} if semantic else set()
            # The loader is an internal, source-replayed selected-version
            # snapshot adapter. A report/client rule ID is never sufficient.
            for rule in known:
                if (rule.status == "verified" and rule.semantics is not None and rule.property_id in facts.defect_properties and
                        rule.semantics.condition is None and rule.semantics.constraint.operator == "eq" and
                        set(rule.semantics.scope.axes) <= {"roles", "characters"}):
                    axis = rule.semantics.scope.axes.get("roles")
                    characters = rule.semantics.scope.axes.get("characters")
                    # Object IDs alone do not prove which script occurs in the
                    # selected substring. Leave script-limited rules unresolved.
                    all_characters = rule.character_scope == "all" and (characters is None or not characters.exclude and
                        (characters.include is None or set(characters.include) == set(CHARACTERS)))
                    if all_characters and roles and all((axis is None or (not axis.include or role in axis.include) and role not in axis.exclude) for role in roles):
                        facts.existing_rule_ids.append(rule.rule_id)
            facts.existing_rule_ids = list(dict.fromkeys(facts.existing_rule_ids))
            if facts.existing_rule_ids:
                facts.kind = "execution_defect"; facts.missing_fields = []
                facts.reason = "已关联此版本的已确认规则，记录为执行问题；实际格式仍需后续复核，尚未生成新规则或修改论文。"
        return facts

    def draft(self, task_id, version_id, submission: FeedbackSubmission):
        context = self.feedback.context(task_id, version_id)
        if (submission.task_id, submission.base_version_id) != (task_id, version_id):
            raise FeedbackError("stale_base_version", "需求预览路径与提交版本不一致。")
        self.feedback._check_binding(submission, context)
        if self.versions.working_version_id(task_id) != version_id:
            raise FeedbackError("stale_base_version", "历史版本只能查看已保存反馈。")
        source_hash = content_hash(submission.model_dump(mode="json"))
        initial = interpret(submission.raw_text, submission.requested_scope, source_hash)
        selected_ids, target_status, text, semantic, selected_texts = None, "none", None, None, None
        if initial.kind not in {"question", "out_of_scope"}:
            text, semantic = self._indexes(context)
            if submission.selection:
                target_status = "unavailable"
                if self.indexes:
                    pdf = self.indexes.pdf(self.versions.artifact_path(task_id, version_id, "preview"), sorted({s.page for s in submission.selection.spans}))
                    matches = find_matches(text, verify_hint(submission.selection, context, pdf), context)
                    if len(matches) == 1 and matches[0].supported:
                        selected_ids = list(dict.fromkeys(r.object_id for r in matches[0].ranges))
                        selected_texts = self._selected_texts(matches[0].ranges)
                        target_status = "pending_confirmation" if matches[0].requires_confirmation or len(submission.selection.spans) > 1 else "ready"
                    elif matches: target_status = "pending_confirmation"
        facts = self._facts(submission, source_hash, context, text, semantic, selected_ids)
        reviews = self._scopes(facts, text, semantic, selected_ids, selected_texts)
        if target_status == "pending_confirmation" and facts.kind not in {"question", "out_of_scope", "execution_defect"}:
            facts.kind = "clarification_needed"; facts.missing_fields = list(dict.fromkeys([*facts.missing_fields, "selection_target"]))
            facts.reason = "需求已解析；目标位置需在保存反馈后确认，尚未执行修改。"
        if self.feedback.context(task_id, version_id) != context or self.versions.working_version_id(task_id) != version_id:
            raise FeedbackError("stale_preview", "需求预览期间版本依据发生变化。")
        return seal_contract(FeedbackDraftReview, dict(schema_version="feedback-draft-review/1.0", task_id=task_id,
            base_version_id=version_id, version_context_id=context.context_id, source_submission_sha256=source_hash,
            parser_id=PARSER_ID, parser_version=PARSER_VERSION, kind=facts.kind, candidates=facts.candidates,
            understood=facts.understood, missing_fields=facts.missing_fields, scope_reviews=reviews,
            existing_rule_ids=facts.existing_rule_ids, target_status=target_status, reason=facts.reason), "review_id")

    @staticmethod
    def _scopes(facts, text, semantic, selected_ids, selected_texts=None):
        if facts.kind in {"question", "out_of_scope", "execution_defect"}: return []
        if text is None or semantic is None:
            facts.kind = "clarification_needed"; facts.missing_fields = list(dict.fromkeys([*facts.missing_fields, "scope_index"]))
            facts.reason = "已识别格式信息；本地范围索引未配置，无法核对实际影响范围。"
            return []
        return build_scopes(facts, text, semantic, selected_ids, selected_texts)

    def _compile(self, record, context, facts, text, semantic, selected_ids, selected_texts=None):
        facts = deepcopy(facts)
        reviews = self._scopes(facts, text, semantic, selected_ids, selected_texts)
        result = seal_contract(FeedbackParseResult, dict(schema_version="feedback-parse-result/1.0",
            task_id=context.task_id, feedback_id=record.feedback_id, version_context_id=context.context_id,
            source_submission_sha256=record.source_submission_sha256, parser_id=PARSER_ID, parser_version=PARSER_VERSION,
            kind=facts.kind, candidates=facts.candidates, understood=facts.understood, missing_fields=facts.missing_fields,
            existing_rule_ids=facts.existing_rule_ids, scope_reviews=reviews, reason=facts.reason), "result_id")
        validate_parse_result(record, context, result, known_rule_ids=set(facts.existing_rule_ids))
        return result

    @staticmethod
    def _answer(row):
        try:
            answer = FeedbackConfirmationRequest.model_validate_json(row["payload_json"])
            if (content_hash(answer.model_dump(mode="json")) != row["payload_sha256"] or answer.task_id != row["task_id"]
                    or answer.feedback_id != row["feedback_id"] or answer.request_id != row["request_id"]
                    or answer.expected_parse_result_id != row["source_result_id"] or answer.answer.action != row["action"]):
                raise ValueError()
            return answer
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "反馈补充或范围确认记录无法通过校验。") from error

    @staticmethod
    def _apply(record, context, result, facts, answer, selected_ids):
        validate_confirmation(record, context, result, answer, known_rule_ids=set(result.existing_rule_ids))
        action = answer.answer
        if action.action == "clarify_format":
            if not set(result.missing_fields) <= {"value", "property_id"} or (record.submission.selection and selected_ids is None):
                raise FeedbackError("needs_user_input", "请先确认目标，或修改原话和范围后重新保存；不能用补值绕过未知限制。")
            prior = next((p for p in facts.understood if p.candidate_id == action.format.candidate_id), None)
            if prior is None:
                raise FeedbackError("needs_user_input", "只能补齐当前展示的缺值条目，不能改写完整候选。")
            after = action.format
            if (after.requested_scope != record.submission.requested_scope or after.character_scope != "all"
                    or after.applicability_scope is not None or after.semantic_role != prior.semantic_role
                    or prior.property_id is not None and after.property_id != prior.property_id
                    or prior.value is not None and after.value != prior.value):
                raise FeedbackError("needs_user_input", "补充格式不能改变已理解的属性、值、角色、字符条件或原始范围。")
            facts.understood = [p for p in facts.understood if p.candidate_id != prior.candidate_id]
            facts.candidates.append(after)
            facts.missing_fields = [key for key in facts.missing_fields if key not in {"value", "property_id", "semantic_role"}]
            if any(p.value is None for p in facts.understood): facts.missing_fields.append("value")
            if any(p.property_id is None for p in facts.understood): facts.missing_fields.append("property_id")
            facts.kind = "clarification_needed" if facts.missing_fields else "new_rule"
            facts.reason = "已按结构化补充得到类型化格式候选；仍需范围及冲突校验，尚未执行修改。"
        elif action.action == "confirm_scope":
            required = {r.review_id for r in result.scope_reviews if r.requires_confirmation}
            if result.kind != "new_rule" or not set(action.accepted_review_ids) <= required:
                raise FeedbackError("needs_user_input", "只能确认已完整解析、已展示且待确认的实际范围。")
        else:
            raise FeedbackError("needs_user_input", "位置选择请使用专用的候选确认入口。")

    def _fresh(self, task_id, version_id, feedback_id, *, decision_limit=None, selection_id=None):
        record = self.feedback.get(task_id, version_id, feedback_id)
        context = self.feedback.context(task_id, version_id)
        initial = interpret(record.submission.raw_text, record.submission.requested_scope, record.source_submission_sha256)
        selection, selected_ids, text, semantic, selected_texts = None, None, None, None, None
        if initial.kind not in {"question", "out_of_scope"}:
            if record.submission.selection and self.indexes:
                selection = self.selections.get(task_id, version_id, feedback_id)
                if selection_id is not None and selection.resolution_id != selection_id:
                    original = self.selections._fresh(task_id, version_id, feedback_id)[3]
                    if original.resolution_id != selection_id:
                        raise FeedbackError("validation_failed", "历史目标结果无法从原文件重放。")
                    selection = original
                if selection.anchor:
                    selected_ids = list(dict.fromkeys(r.object_id for r in selection.anchor.ranges))
                    selected_texts = self._selected_texts(selection.anchor.ranges)
            text, semantic = self._indexes(context)
        facts = self._facts(record.submission, record.source_submission_sha256, context, text, semantic, selected_ids)
        with self.versions._transaction() as connection:
            rows = connection.execute("SELECT * FROM feedback_processing_decisions WHERE feedback_id=? ORDER BY sequence", (feedback_id,)).fetchall()
        if len(rows) > 128 or [r["sequence"] for r in rows] != list(range(1, len(rows) + 1)):
            raise FeedbackError("validation_failed", "反馈决定历史不连续或超过限制。")
        if decision_limit is not None:
            if not 0 <= decision_limit <= len(rows):
                raise FeedbackError("validation_failed", "历史反馈决定前缀不存在。")
            rows = rows[:decision_limit]
        confirmed = set()
        result = self._compile(record, context, facts, text, semantic, selected_ids, selected_texts)
        for row in rows:
            answer = self._answer(row)
            self._apply(record, context, result, facts, answer, selected_ids)
            if answer.answer.action == "confirm_scope": confirmed.update(answer.answer.accepted_review_ids)
            result = self._compile(record, context, facts, text, semantic, selected_ids, selected_texts)
        if self.feedback.context(task_id, version_id) != context:
            raise FeedbackError("stale_preview", "反馈解析期间版本依据发生变化。")
        confirmed.intersection_update(r.review_id for r in result.scope_reviews)
        analysis = seal_contract(FeedbackAnalysis, dict(schema_version="feedback-analysis/1.0", interpretation=result,
            selection=selection, confirmed_review_ids=sorted(confirmed), decision_count=len(rows)), "analysis_id")
        return record, context, facts, text, semantic, selected_ids, selected_texts, analysis

    def _save(self, connection, result):
        encoded = canonical_bytes(result.model_dump(mode="json")).decode()
        row = connection.execute("SELECT * FROM feedback_parse_results WHERE feedback_id=? AND result_id=? AND engine_fingerprint=?",
            (result.feedback_id, result.result_id, self.fingerprint)).fetchone()
        digest = content_hash(result.model_dump(mode="json"))
        if row and (row["payload_json"] != encoded or row["payload_sha256"] != digest):
            raise FeedbackError("validation_failed", "历史反馈解析与原话重放不一致。")
        if not row:
            connection.execute("INSERT INTO feedback_parse_results VALUES (?, ?, ?, ?, ?, ?)",
                (result.feedback_id, result.result_id, self.fingerprint, encoded, digest, _utc_now()))

    def get(self, task_id, version_id, feedback_id):
        with self._lock:
            record, context, _, _, _, _, _, analysis = self._fresh(task_id, version_id, feedback_id)
            with self.versions._transaction() as connection:
                self.selections._check_transaction(connection, record, context, active=False)
                self._save(connection, analysis.interpretation)
            return analysis

    def confirm(self, task_id, version_id, feedback_id, answer: FeedbackConfirmationRequest):
        answer = FeedbackConfirmationRequest.model_validate_json(answer.model_dump_json())
        if (task_id, version_id, feedback_id) != (answer.task_id, answer.base_version_id, answer.feedback_id) or not answer.raw_answer.strip():
            raise FeedbackError("needs_user_input", "补充必须绑定原反馈并包含明确答案。")
        with self._lock:
            record, context, facts, text, semantic, selected_ids, selected_texts, analysis = self._fresh(task_id, version_id, feedback_id)
            with self.versions._transaction() as connection:
                self.selections._check_transaction(connection, record, context, active=False)
                prior = connection.execute("SELECT * FROM feedback_processing_decisions WHERE task_id=? AND request_id=?", (task_id, answer.request_id)).fetchone()
                if prior:
                    if self._answer(prior) != answer: raise FeedbackError("blocked_conflict", "请求 ID 已用于不同的反馈答案。")
                    return analysis
            self._apply(record, context, analysis.interpretation, facts, answer, selected_ids)
            updated = self._compile(record, context, facts, text, semantic, selected_ids, selected_texts)
            confirmed = set(analysis.confirmed_review_ids)
            if answer.answer.action == "confirm_scope": confirmed.update(answer.answer.accepted_review_ids)
            with self.versions._transaction() as connection:
                self.selections._check_transaction(connection, record, context, active=False)
                prior = connection.execute("SELECT * FROM feedback_processing_decisions WHERE task_id=? AND request_id=?", (task_id, answer.request_id)).fetchone()
                if prior:
                    if self._answer(prior) != answer: raise FeedbackError("blocked_conflict", "请求 ID 已用于不同的反馈答案。")
                else:
                    self.selections._check_transaction(connection, record, context, active=True)
                    count = connection.execute("SELECT COUNT(*) FROM feedback_processing_decisions WHERE feedback_id=?", (feedback_id,)).fetchone()[0]
                    if count != analysis.decision_count:
                        raise FeedbackError("blocked_conflict", "反馈已收到其他答案，请重新加载。")
                    if count >= 128: raise FeedbackError("needs_user_input", "此反馈补充次数过多，请拆开新建反馈。")
                    self._save(connection, analysis.interpretation); self._save(connection, updated)
                    payload = answer.model_dump(mode="json")
                    connection.execute("INSERT INTO feedback_processing_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (new_id(), task_id, feedback_id, answer.request_id, count + 1, answer.answer.action,
                         answer.expected_parse_result_id, canonical_bytes(payload).decode(), content_hash(payload), _utc_now()))
            if prior:
                return self.get(task_id, version_id, feedback_id)
            return seal_contract(FeedbackAnalysis, dict(schema_version="feedback-analysis/1.0", interpretation=updated,
                selection=analysis.selection, confirmed_review_ids=sorted(confirmed & {r.review_id for r in updated.scope_reviews}),
                decision_count=analysis.decision_count + 1), "analysis_id")
