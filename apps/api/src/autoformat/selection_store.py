"""Append-only selection evidence and target decisions, replayed from source.

Loading a checksum-valid anchor never authorizes an edit. Every retrieval
repeats trusted PDF/DOCX indexing and rebuilds the result and any target choice.
"""
from __future__ import annotations

import json
import threading

from .feedback_contracts import SelectionTargetConfirmation, SelectionResolution, canonical_bytes, content_hash
from .feedback_store import FeedbackError, FeedbackStore
from .feedback_validation import validate_selection_resolution
from .selection_indexes import SelectionIndexes
from .selection_resolver import find_matches, resolution, verify_hint
from .version_store import _utc_now, new_id


class SelectionStore:
    def __init__(self, feedback: FeedbackStore, indexes: SelectionIndexes):
        self.feedback, self.indexes = feedback, indexes
        self.versions = feedback.versions
        self._lock = threading.RLock()
        with self.versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS selection_resolutions (
                feedback_id TEXT NOT NULL REFERENCES feedback_submissions(feedback_id),
                resolution_id TEXT NOT NULL, engine_fingerprint TEXT NOT NULL,
                version_context_id TEXT NOT NULL, source_submission_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(feedback_id, resolution_id, engine_fingerprint))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS selection_target_decisions (
                decision_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                feedback_id TEXT NOT NULL REFERENCES feedback_submissions(feedback_id),
                request_id TEXT NOT NULL, original_resolution_id TEXT NOT NULL,
                result_resolution_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(task_id, request_id), UNIQUE(feedback_id))""")

    def _fresh(self, task_id, version_id, feedback_id):
        record = self.feedback.get(task_id, version_id, feedback_id)
        context = self.feedback.context(task_id, version_id)
        hint = record.submission.selection
        matches = []
        if hint is not None:
            pdf = self.indexes.pdf(self.versions.artifact_path(task_id, version_id, "preview"),
                                   sorted({span.page for span in hint.spans}))
            evidence = verify_hint(hint, context, pdf)
            index = self.indexes.docx(self.versions.artifact_path(task_id, version_id, "docx"))
            matches = find_matches(index, evidence, context)
        result = resolution(record, context, matches)
        # Recheck after external processes; an old file cannot pass a new binding.
        after = self.feedback.context(task_id, version_id)
        if after != context:
            raise FeedbackError("stale_preview", "定位期间预览依据已变化，请重新加载。")
        validate_selection_resolution(record, context, result)
        return record, context, matches, result

    def _save(self, connection, record, context, result):
        encoded = canonical_bytes(result.model_dump(mode="json")).decode("utf-8")
        row = connection.execute("SELECT * FROM selection_resolutions WHERE feedback_id=? AND resolution_id=? AND engine_fingerprint=?",
            (record.feedback_id, result.resolution_id, self.indexes.fingerprint)).fetchone()
        if row is not None:
            if (row["payload_json"] != encoded or row["payload_sha256"] != content_hash(result.model_dump(mode="json"))
                    or row["version_context_id"] != context.context_id or row["source_submission_sha256"] != record.source_submission_sha256):
                raise FeedbackError("validation_failed", "历史定位结果与原文件重放不一致。")
            return
        connection.execute("INSERT INTO selection_resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (record.feedback_id, result.resolution_id, self.indexes.fingerprint, context.context_id,
             record.source_submission_sha256, encoded, content_hash(result.model_dump(mode="json")), _utc_now()))

    def _check_transaction(self, connection, record, context, *, active: bool):
        row = connection.execute("SELECT * FROM versions WHERE task_id=? AND version_id=?",
            (context.task_id, context.base_version_id)).fetchone()
        current = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (context.task_id,)).fetchone()
        source = connection.execute("SELECT * FROM feedback_submissions WHERE feedback_id=?", (record.feedback_id,)).fetchone()
        if (active and (current is None or current[0] != context.base_version_id)):
            raise FeedbackError("stale_base_version", "当前工作版本已改变，请回到对应工作起点后确认。")
        if (row is None or source is None or self.feedback._record(source) != record or row["status"] != "ready"
                or row["docx_sha256"] != context.base_docx_sha256 or row["preview_sha256"] != context.preview_pdf_sha256
                or row["preview_metadata_sha256"] != context.preview_metadata_sha256
                or row["preview_artifact_id"] != context.preview_artifact_id
                or row["renderer_id"] != context.renderer_id or row["renderer_version"] != context.renderer_version
                or json.loads(row["references_json"])["rules_snapshot_id"] != context.rules_snapshot_id
                or json.loads(row["references_json"])["brief_version_id"] != context.brief_version_id
                or json.loads(row["references_json"]).get("feedback_rules_snapshot_id") != context.feedback_rules_snapshot_id
                or not all(self.versions._matches_hash(row[path], row[digest]) for path, digest in (
                    ("docx_path", "docx_sha256"), ("preview_path", "preview_sha256"), ("preview_metadata_path", "preview_metadata_sha256")))):
            raise FeedbackError("stale_preview", "定位依据在处理中发生变化，请重新加载。")

    @staticmethod
    def _decision(row) -> SelectionTargetConfirmation:
        try:
            payload = json.loads(row["payload_json"])
            answer = SelectionTargetConfirmation.model_validate_json(row["payload_json"])
            if (content_hash(payload) != row["payload_sha256"] or answer.task_id != row["task_id"]
                    or answer.feedback_id != row["feedback_id"] or answer.request_id != row["request_id"]
                    or answer.expected_resolution_id != row["original_resolution_id"]):
                raise ValueError()
            return answer
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "目标确认记录无法通过完整性校验。") from error

    @staticmethod
    def _chosen(record, context, matches, original, answer):
        if (answer.task_id != context.task_id or answer.base_version_id != context.base_version_id
                or answer.feedback_id != record.feedback_id or answer.expected_base_docx_sha256 != context.base_docx_sha256
                or answer.expected_context_id != context.context_id or answer.expected_resolution_id != original.resolution_id):
            raise FeedbackError("stale_preview", "目标候选或版本依据已变化，请重新定位。")
        if original.status != "ambiguous" or answer.candidate_id not in {candidate.candidate_id for candidate in original.candidates}:
            raise FeedbackError("needs_user_input", "只能确认本次展示的一个目标候选。")
        result = resolution(record, context, matches, chosen=answer.candidate_id)
        validate_selection_resolution(record, context, result)
        return result

    def get(self, task_id: str, version_id: str, feedback_id: str) -> SelectionResolution:
        with self._lock:
            record, context, matches, original = self._fresh(task_id, version_id, feedback_id)
            with self.versions._transaction() as connection:
                self._check_transaction(connection, record, context, active=False)
                self._save(connection, record, context, original)
                row = connection.execute("SELECT * FROM selection_target_decisions WHERE feedback_id=?", (feedback_id,)).fetchone()
                if row is None:
                    return original
                result = self._chosen(record, context, matches, original, self._decision(row))
                if result.resolution_id != row["result_resolution_id"]:
                    raise FeedbackError("validation_failed", "已确认目标与原文件重放不一致。")
                self._save(connection, record, context, result)
                return result

    def confirm(self, task_id: str, version_id: str, feedback_id: str, answer: SelectionTargetConfirmation) -> SelectionResolution:
        try:
            answer = SelectionTargetConfirmation.model_validate_json(answer.model_dump_json())
        except ValueError as error:
            raise FeedbackError("needs_user_input", "目标选择不符合版本化契约。") from error
        if (task_id, version_id, feedback_id) != (answer.task_id, answer.base_version_id, answer.feedback_id):
            raise FeedbackError("stale_base_version", "目标选择路径与原反馈不一致。")
        with self._lock:
            record, context, matches, original = self._fresh(task_id, version_id, feedback_id)
            result = self._chosen(record, context, matches, original, answer)
            payload = answer.model_dump(mode="json")
            with self.versions._transaction() as connection:
                self._check_transaction(connection, record, context, active=False)
                prior = connection.execute("SELECT * FROM selection_target_decisions WHERE task_id=? AND request_id=?",
                    (task_id, answer.request_id)).fetchone()
                if prior is not None:
                    if self._decision(prior) != answer or prior["result_resolution_id"] != result.resolution_id:
                        raise FeedbackError("blocked_conflict", "请求 ID 已用于不同的目标选择。")
                    return result
                if connection.execute("SELECT 1 FROM selection_target_decisions WHERE feedback_id=?", (feedback_id,)).fetchone():
                    raise FeedbackError("blocked_conflict", "此反馈已确认目标，请读取已有结果。")
                self._check_transaction(connection, record, context, active=True)
                self._save(connection, record, context, original)
                self._save(connection, record, context, result)
                connection.execute("INSERT INTO selection_target_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id(), task_id, feedback_id, answer.request_id, original.resolution_id, result.resolution_id,
                     canonical_bytes(payload).decode("utf-8"), content_hash(payload), _utc_now()))
            return result
