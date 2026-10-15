"""Switch work origins without changing artifacts or rewriting rule history."""
import json

from .feedback_contracts import canonical_bytes, content_hash
from .feedback_store import FeedbackError
from .reports import validate_report
from .workspace_contracts import VersionContinuationRequest, VersionContinuation


class VersionWorkspace:
    def __init__(self, feedback, rules):
        self.feedback, self.versions = feedback, feedback.versions
        self.rules = rules
        with self.versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS version_continuations (
                task_id TEXT NOT NULL, request_id TEXT NOT NULL, request_json TEXT NOT NULL,
                result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                PRIMARY KEY(task_id, request_id))""")

    def continue_from(self, request):
        request = VersionContinuationRequest.model_validate_json(request.model_dump_json())
        encoded = canonical_bytes(request.model_dump(mode="json")).decode()
        # A replay returns the receipt without moving a newer work origin back.
        with self.versions._transaction() as connection:
            prior = connection.execute("SELECT * FROM version_continuations WHERE task_id=? AND request_id=?",
                (request.task_id, request.request_id)).fetchone()
        if prior is not None:
            return self._replay(prior, request, encoded)
        context = self.feedback.context(request.task_id, request.version_id)
        if context.base_docx_sha256 != request.expected_docx_sha256:
            raise FeedbackError("stale_base_version", "所选版本文件已变化，请重新核对。")
        report = json.loads(self.versions.artifact_path(request.task_id, request.version_id, "report_json").read_text(encoding="utf-8"))
        validate_report(report)
        if report["task_id"] != request.task_id or report["version_id"] != request.version_id or report["output_docx_sha256"] != context.base_docx_sha256:
            raise FeedbackError("validation_failed", "历史报告与所选版本不一致。")
        changing = request.expected_working_version_id != request.version_id
        previous, restart = self.rules.prepare_restart(request.task_id, request.version_id) if changing else (None, None)
        result = VersionContinuation(schema_version="version-continuation/1.0", request_id=request.request_id,
            task_id=request.task_id, continued_version_id=request.version_id,
            previous_working_version_id=request.expected_working_version_id,
            working_version_id=request.version_id, replayed=False)
        payload = result.model_dump(mode="json")
        with self.versions._transaction() as connection:
            prior = connection.execute("SELECT * FROM version_continuations WHERE task_id=? AND request_id=?",
                (request.task_id, request.request_id)).fetchone()
            if prior is not None:
                return self._replay(prior, request, encoded, connection)
            active = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (request.task_id,)).fetchone()
            row = connection.execute("SELECT * FROM versions WHERE task_id=? AND version_id=?", (request.task_id, request.version_id)).fetchone()
            if active is None or active[0] != request.expected_working_version_id:
                raise FeedbackError("stale_base_version", "工作起点已被其他操作更改，请刷新后再选择。")
            try:
                references = json.loads(row["references_json"]) if row else {}
                if (references["rules_snapshot_id"], references["brief_version_id"], references.get("feedback_rules_snapshot_id")) != (
                        context.rules_snapshot_id, context.brief_version_id, context.feedback_rules_snapshot_id):
                    raise ValueError()
            except (ValueError, TypeError, KeyError) as error:
                raise FeedbackError("stale_base_version", "所选版本的规则依据已变化，请刷新。") from error
            if (row is None or row["kind"] != "output" or row["status"] != "ready" or
                    row["docx_sha256"] != request.expected_docx_sha256 or
                    row["preview_sha256"] != context.preview_pdf_sha256 or
                    row["preview_metadata_sha256"] != context.preview_metadata_sha256 or
                    not all(self.versions._matches_hash(row[p], row[h]) for p, h in (
                        ("docx_path", "docx_sha256"), ("preview_path", "preview_sha256"),
                        ("preview_metadata_path", "preview_metadata_sha256"),
                        ("report_json_path", "report_json_sha256"), ("report_markdown_path", "report_markdown_sha256")))):
                raise FeedbackError("validation_failed", "所选版本的论文、预览或报告无法通过校验。")
            connection.execute("INSERT INTO version_continuations VALUES (?,?,?,?,?)",
                (request.task_id, request.request_id, encoded, canonical_bytes(payload).decode(), content_hash(payload)))
            if changing: self.rules.commit_restart(connection, request, previous, restart)
            connection.execute("UPDATE tasks SET working_version_id=? WHERE task_id=?", (request.version_id, request.task_id))
        return result

    def _replay(self, row, request, encoded, connection=None):
        if row["request_json"] != encoded:
            raise FeedbackError("blocked_conflict", "继续编辑请求 ID 已用于不同内容。")
        try:
            result = VersionContinuation.model_validate_json(row["result_json"])
            if (content_hash(result.model_dump(mode="json")) != row["result_sha256"] or
                    (result.task_id, result.request_id, result.continued_version_id, result.previous_working_version_id) !=
                    (request.task_id, request.request_id, request.version_id, request.expected_working_version_id) or
                    result.working_version_id != request.version_id or result.replayed):
                raise ValueError()
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "继续编辑回执无法通过校验。") from error
        current = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (request.task_id,)).fetchone()[0] if connection else self.versions.working_version_id(request.task_id)
        return result.model_copy(update={"working_version_id": current, "replayed": True})
