"""Append-only feedback intake bound to immutable, published DOCX versions.

This stage stores input only. It neither resolves PDF hints nor calls a parser
or editor, and cannot receive client-supplied anchors or executable rules.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from .feedback_contracts import (
    FeedbackRecord, FeedbackReceipt, FeedbackSubmission, FeedbackVersionContext,
    canonical_bytes, content_hash,
)
from .preview import PreviewArtifact, _sha256
from .version_store import VersionStore, _require_id, _utc_now, new_id


class FeedbackError(Exception):
    def __init__(self, status: str, reason: str):
        self.status = status
        super().__init__(reason)


class FeedbackStore:
    def __init__(self, versions: VersionStore, *, max_request_bytes: int = 128 * 1024):
        if type(max_request_bytes) is not int or max_request_bytes < 1:
            raise ValueError("Feedback request limit must be a positive integer.")
        self.versions = versions
        self.max_request_bytes = max_request_bytes
        with versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_submissions (
                feedback_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                base_version_id TEXT NOT NULL REFERENCES versions(version_id),
                request_id TEXT NOT NULL,
                version_context_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(task_id, request_id))""")

    def context(self, task_id: str, version_id: str) -> FeedbackVersionContext:
        """Read version references, never AcademicDecisionStore's task-wide head."""
        version = self.versions.get_version(task_id, version_id)
        if version.kind != "output" or version.status != "ready" or version.references is None:
            raise FeedbackError("needs_user_input", "先发布初稿 V1，再提交预览反馈。")
        self.versions.artifact_path(task_id, version_id, "docx")
        pdf = self.versions.artifact_path(task_id, version_id, "preview")
        metadata_path = self.versions.artifact_path(task_id, version_id, "preview_metadata")
        try:
            metadata = PreviewArtifact(**json.loads(metadata_path.read_text(encoding="utf-8")))
            if (metadata.schema_version != "preview-artifact/1.0"
                    or metadata.artifact_id != version.preview_artifact_id
                    or metadata.source_sha256 != version.docx_sha256
                    or metadata.pdf_sha256 != _sha256(pdf)
                    or metadata.pdf_relative_path != f"artifacts/previews/{metadata.artifact_id}.pdf"
                    or metadata.renderer_id != version.renderer_id
                    or metadata.renderer_version != version.renderer_version
                    or type(metadata.selectable_text_chars) is not int
                    or metadata.selectable_text_chars < 1):
                raise ValueError("Preview metadata differs from the published version.")
            payload = {
                "schema_version": "feedback-version-context/1.0",
                "task_id": task_id, "base_version_id": version_id,
                "base_docx_sha256": version.docx_sha256,
                "preview_artifact_id": metadata.artifact_id,
                "preview_pdf_sha256": metadata.pdf_sha256,
                "preview_metadata_sha256": _sha256(metadata_path),
                "renderer_id": metadata.renderer_id,
                "renderer_version": metadata.renderer_version,
                "page_count": metadata.page_count,
                "rules_snapshot_id": version.references.rules_snapshot_id,
                "brief_version_id": version.references.brief_version_id,
                "feedback_rules_snapshot_id": version.references.feedback_rules_snapshot_id,
            }
            return FeedbackVersionContext(context_id=content_hash(payload), **payload)
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "预览与所选论文版本的绑定无法通过校验。") from error

    @staticmethod
    def _check_binding(request: FeedbackSubmission, context: FeedbackVersionContext) -> None:
        if (request.task_id != context.task_id or request.base_version_id != context.base_version_id
                or request.expected_base_docx_sha256 != context.base_docx_sha256):
            raise FeedbackError("stale_base_version", "反馈基础版本已变化，请重新查看并定位。")
        if (request.preview_artifact_id != context.preview_artifact_id
                or request.expected_preview_pdf_sha256 != context.preview_pdf_sha256):
            raise FeedbackError("stale_preview", "反馈不属于此版本的预览，请重新选择文字。")
        if request.expected_context_id != context.context_id:
            raise FeedbackError("stale_base_version", "反馈规则依据或预览上下文已变化，请刷新。")
        if request.selection is not None and any(span.page > context.page_count for span in request.selection.spans):
            raise FeedbackError("needs_user_input", "所选页码超出此预览的页数。")

    @staticmethod
    def _record(row) -> FeedbackRecord:
        try:
            raw = json.loads(row["payload_json"])
            if content_hash(raw) != row["payload_sha256"]:
                raise ValueError("Feedback record hash changed.")
            record = FeedbackRecord.model_validate_json(row["payload_json"])
            submission = record.submission
            if (record.feedback_id != row["feedback_id"] or record.created_at != row["created_at"]
                    or submission.task_id != row["task_id"] or submission.base_version_id != row["base_version_id"]
                    or submission.request_id != row["request_id"]
                    or submission.expected_context_id != row["version_context_id"]):
                raise ValueError("Feedback row identity differs from its envelope.")
            return record
        except (ValueError, KeyError, TypeError) as error:
            raise FeedbackError("validation_failed", "历史反馈记录无法通过完整性校验。") from error

    @staticmethod
    def receipt(record: FeedbackRecord, *, replayed: bool = False) -> FeedbackReceipt:
        submission = record.submission
        return FeedbackReceipt(
            schema_version="feedback-receipt/1.0", feedback_id=record.feedback_id,
            task_id=submission.task_id, base_version_id=submission.base_version_id,
            request_id=submission.request_id, version_context_id=submission.expected_context_id,
            source_submission_sha256=record.source_submission_sha256,
            created_at=record.created_at, status="received", replayed=replayed,
            next_action="pending_feedback_processing",
        )

    def submit(self, task_id: str, version_id: str, request: FeedbackSubmission) -> FeedbackReceipt:
        # Revalidate even internal callers: frozen Pydantic models still contain
        # mutable nested lists and model_copy(update=...) bypasses validation.
        try:
            request = FeedbackSubmission.model_validate_json(request.model_dump_json())
        except ValidationError as error:
            raise FeedbackError("needs_user_input", "反馈不符合版本化契约。") from error
        if (task_id, version_id) != (request.task_id, request.base_version_id):
            raise FeedbackError("stale_base_version", "反馈路径与基础版本不一致。")
        encoded_request = canonical_bytes(request.model_dump(mode="json"))
        if len(encoded_request) > self.max_request_bytes:
            raise FeedbackError("needs_user_input", "反馈超过当前配置的大小限制。")
        context = self.context(task_id, version_id)
        self._check_binding(request, context)
        # The one transaction checks the current pointer and inserts once, so
        # two concurrent submissions with the same ID cannot create duplicates.
        with self.versions._transaction() as connection:
            prior = connection.execute(
                "SELECT * FROM feedback_submissions WHERE task_id=? AND request_id=?",
                (task_id, request.request_id),
            ).fetchone()
            if prior is not None:
                record = self._record(prior)
                if canonical_bytes(record.submission.model_dump(mode="json")) != encoded_request:
                    raise FeedbackError("blocked_conflict", "请求 ID 已用于不同的反馈。")
                self._check_binding(record.submission, context)
                return self.receipt(record, replayed=True)
            active = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            row = connection.execute("SELECT * FROM versions WHERE task_id=? AND version_id=?", (task_id, version_id)).fetchone()
            if (active is None or active[0] != version_id or row is None or row["status"] != "ready"
                    or row["docx_sha256"] != context.base_docx_sha256
                    or row["preview_artifact_id"] != context.preview_artifact_id
                    or row["preview_sha256"] != context.preview_pdf_sha256
                    or row["preview_metadata_sha256"] != context.preview_metadata_sha256
                    or row["renderer_id"] != context.renderer_id
                    or row["renderer_version"] != context.renderer_version):
                raise FeedbackError("stale_base_version", "当前工作版本已变化，请刷新后提交。")
            references = json.loads(row["references_json"])
            if (references["rules_snapshot_id"] != context.rules_snapshot_id
                    or references["brief_version_id"] != context.brief_version_id
                    or not all(self.versions._matches_hash(row[path], row[digest]) for path, digest in (
                        ("docx_path", "docx_sha256"), ("preview_path", "preview_sha256"),
                        ("preview_metadata_path", "preview_metadata_sha256")))):
                raise FeedbackError("stale_base_version", "基础文件或规则依据已变化，请重新核对。")
            record = FeedbackRecord(
                schema_version="feedback-record/1.0", feedback_id=new_id(), submission=request,
                source_submission_sha256=content_hash(request.model_dump(mode="json")),
                created_at=_utc_now(), status="received",
            )
            payload = record.model_dump(mode="json")
            connection.execute("INSERT INTO feedback_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (record.feedback_id, task_id, version_id, request.request_id, context.context_id,
                 canonical_bytes(payload).decode("utf-8"), content_hash(payload), record.created_at))
        return self.receipt(record)

    def get(self, task_id: str, version_id: str, feedback_id: str) -> FeedbackRecord:
        _require_id(feedback_id, "feedback")
        context = self.context(task_id, version_id)
        with self.versions._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM feedback_submissions WHERE task_id=? AND base_version_id=? AND feedback_id=?",
                (task_id, version_id, feedback_id),
            ).fetchone()
        if row is None:
            raise FeedbackError("needs_user_input", "此版本没有所请求的反馈。")
        record = self._record(row)
        self._check_binding(record.submission, context)
        return record

    def list_receipts(self, task_id: str, version_id: str) -> list[FeedbackReceipt]:
        context = self.context(task_id, version_id)
        with self.versions._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback_submissions WHERE task_id=? AND base_version_id=? ORDER BY rowid",
                (task_id, version_id),
            ).fetchall()
        records = [self._record(row) for row in rows]
        for record in records:
            self._check_binding(record.submission, context)
        return [self.receipt(record) for record in records]
