"""Local immutable version tree with staged artifact publication."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .preview import PreviewArtifact, PreviewError, _sha256, inspect_docx_for_render
from .reports import ReportError, render_markdown, validate_report


_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_REPORT_BYTES = 10 * 1024 * 1024
_MAX_PDF_BYTES = 100 * 1024 * 1024


class VersionStoreError(Exception):
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class VersionReferences:
    rules_snapshot_id: str
    brief_version_id: str
    edit_plan_id: str
    font_fingerprint: str
    template_version_id: str | None = None
    decision_version_id: str | None = None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    task_id: str
    version_id: str
    parent_version_id: str | None
    sequence: int
    kind: str
    status: str
    docx_sha256: str
    docx_relative_path: str
    report_json_relative_path: str | None
    report_markdown_relative_path: str | None
    preview_relative_path: str | None
    preview_metadata_relative_path: str | None
    preview_artifact_id: str | None
    renderer_id: str | None
    renderer_version: str | None
    references: VersionReferences | None
    created_at: str
    schema_version: str = "version-node/1.0"


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    task_id: str
    base_version_id: str
    request_id: str
    kind: str
    payload: dict
    created_at: str
    schema_version: str = "decision-event/1.0"


def new_id() -> str:
    return secrets.token_hex(16)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_id(value: str, label: str) -> None:
    if not _ID.fullmatch(value):
        raise VersionStoreError("validation_failed", f"{label} must be a random 128-bit ID.")


def _safe_remove_directory(path: Path, parent: Path, root: Path) -> None:
    """Only remove one immediate, non-redirected child of an owned directory."""
    if (_redirected(parent, root) or
            not parent.resolve().is_relative_to(root)):
        raise VersionStoreError("validation_failed", "Storage cleanup parent is redirected.")
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise VersionStoreError("validation_failed", "Storage directory is redirected.")
    if not path.exists():
        return
    if (not path.is_dir() or path.resolve().parent != parent.resolve() or
            not path.resolve().is_relative_to(root)):
        raise VersionStoreError("validation_failed", "Storage cleanup path is outside its owner.")
    shutil.rmtree(path)


def _redirected(path: Path, root: Path) -> bool:
    cursor = path
    while cursor != root:
        if (cursor.is_symlink() or
                (hasattr(cursor, "is_junction") and cursor.is_junction())):
            return True
        if cursor.parent == cursor:
            return True
        cursor = cursor.parent
    return False


class VersionStore:
    """Stores ready versions only; upstream planners and editors supply candidates."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
            raise VersionStoreError("validation_failed", "Version storage root is redirected.")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        self.tasks_dir = self.root / "tasks"
        self.staging_dir = self.root / ".staging"
        self.tasks_dir.mkdir(exist_ok=True)
        self.staging_dir.mkdir(exist_ok=True)
        if (self.tasks_dir.resolve().parent != self.root or
                self.staging_dir.resolve().parent != self.root):
            raise VersionStoreError("validation_failed", "Version storage child is redirected.")
        self.database = self.root / "versions.sqlite3"
        if self.database.is_symlink():
            raise VersionStoreError("validation_failed", "Version database is redirected.")
        self._initialize_database()
        self.recover()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    working_version_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    parent_version_id TEXT REFERENCES versions(version_id),
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('original', 'output')),
                    status TEXT NOT NULL CHECK (status IN ('ready', 'validation_failed')),
                    docx_path TEXT NOT NULL,
                    docx_sha256 TEXT NOT NULL,
                    report_json_path TEXT,
                    report_json_sha256 TEXT,
                    report_markdown_path TEXT,
                    report_markdown_sha256 TEXT,
                    preview_path TEXT,
                    preview_sha256 TEXT,
                    preview_metadata_path TEXT,
                    preview_metadata_sha256 TEXT,
                    preview_artifact_id TEXT,
                    renderer_id TEXT,
                    renderer_version TEXT,
                    references_json TEXT,
                    request_id TEXT,
                    request_fingerprint TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (task_id, sequence),
                    UNIQUE (task_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    base_version_id TEXT NOT NULL REFERENCES versions(version_id),
                    request_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('answer', 'skip', 'defer', 'consultation')),
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (task_id, request_id)
                );
            """)

    def _artifact_path(self, relative_path: str) -> Path:
        path = self.root / relative_path
        if (_redirected(path, self.root) or
                not path.resolve().is_relative_to(self.root)):
            raise VersionStoreError("validation_failed", "Stored artifact path is redirected.")
        return path

    def _new_stage(self) -> Path:
        stage = self.staging_dir / uuid4().hex
        stage.mkdir()
        return stage

    def create_task(self, source_docx: Path) -> VersionRecord:
        """Copy a checked original into an immutable V0 task directory."""
        if source_docx.is_symlink() or not source_docx.is_file():
            raise VersionStoreError("unsafe_input", "Original DOCX is unavailable or redirected.")
        source_hash = _sha256(source_docx)
        task_id, version_id = new_id(), new_id()
        stage = self._new_stage()
        task_root = self.tasks_dir / task_id
        published = False
        committed = False
        try:
            staged_docx = stage / "versions" / version_id / "document.docx"
            staged_docx.parent.mkdir(parents=True)
            shutil.copyfile(source_docx, staged_docx)
            try:
                staged_hash = inspect_docx_for_render(staged_docx)
            except PreviewError as error:
                raise VersionStoreError(error.status, str(error)) from error
            if _sha256(source_docx) != source_hash or staged_hash != source_hash:
                raise VersionStoreError("unsafe_input", "Original DOCX changed while being stored.")
            created_at = _utc_now()
            docx_path = f"tasks/{task_id}/versions/{version_id}/document.docx"
            with self._transaction() as connection:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?)", (task_id, version_id, created_at)
                )
                connection.execute("""
                    INSERT INTO versions (
                        version_id, task_id, parent_version_id, sequence, kind, status,
                        docx_path, docx_sha256, created_at
                    ) VALUES (?, ?, NULL, 0, 'original', 'ready', ?, ?, ?)
                """, (version_id, task_id, docx_path, source_hash, created_at))
                if task_root.exists():
                    raise VersionStoreError("validation_failed", "Task directory already exists.")
                stage.rename(task_root)
                published = True
            committed = True
            return self.get_version(task_id, version_id)
        except BaseException:
            if published and not committed:
                _safe_remove_directory(task_root, self.tasks_dir, self.root)
            raise
        finally:
            _safe_remove_directory(stage, self.staging_dir, self.root)

    def publish_version(
        self,
        *,
        task_id: str,
        version_id: str,
        parent_version_id: str,
        expected_parent_sha256: str,
        request_id: str,
        candidate_docx: Path,
        report_json: Path,
        report_markdown: Path,
        preview_pdf: Path,
        preview_artifact: PreviewArtifact,
        references: VersionReferences,
    ) -> VersionRecord:
        """Publish one complete output version from a selected parent."""
        for label, value in (("task", task_id), ("version", version_id),
                             ("parent version", parent_version_id), ("request", request_id)):
            _require_id(value, label)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_parent_sha256):
            raise VersionStoreError("validation_failed", "Expected parent hash is invalid.")
        if any(not value for value in (
            references.rules_snapshot_id, references.brief_version_id,
            references.edit_plan_id, references.font_fingerprint,
        )):
            raise VersionStoreError("validation_failed", "Version references are incomplete.")
        references_json = json.dumps(asdict(references), sort_keys=True)
        with self._transaction() as connection:
            prior_request = connection.execute(
                "SELECT version_id, parent_version_id, references_json FROM versions "
                "WHERE task_id=? AND request_id=?", (task_id, request_id),
            ).fetchone()
            if (prior_request is not None and
                    (prior_request["version_id"] != version_id or
                     prior_request["parent_version_id"] != parent_version_id or
                     prior_request["references_json"] != references_json)):
                raise VersionStoreError("blocked_conflict", "Request ID was used for different output.")
        stage = self._new_stage()
        version_root = self.tasks_dir / task_id / "versions"
        final_dir = version_root / version_id
        published = False
        committed = False
        try:
            for candidate in (candidate_docx, report_json, report_markdown, preview_pdf):
                if candidate.is_symlink() or not candidate.is_file():
                    raise VersionStoreError("validation_failed", "A candidate artifact is unavailable.")
            docx = stage / "document.docx"
            markdown = stage / "report.md"
            report = stage / "report.json"
            pdf = stage / preview_artifact.pdf_relative_path
            if (preview_artifact.schema_version != "preview-artifact/1.0" or
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", preview_artifact.artifact_id) or
                    not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", preview_artifact.renderer_id) or
                    not preview_artifact.renderer_version or
                    preview_artifact.pdf_relative_path !=
                    f"artifacts/previews/{preview_artifact.artifact_id}.pdf"):
                raise VersionStoreError("render_failed", "Preview artifact metadata is invalid.")
            pdf.parent.mkdir(parents=True)
            for source, target in ((candidate_docx, docx), (report_json, report),
                                   (report_markdown, markdown), (preview_pdf, pdf)):
                shutil.copyfile(source, target)
            try:
                docx_hash = inspect_docx_for_render(docx)
            except PreviewError as error:
                raise VersionStoreError(error.status, str(error)) from error
            if _sha256(candidate_docx) != docx_hash:
                raise VersionStoreError("validation_failed", "Candidate DOCX changed during staging.")
            report_hash, markdown_hash = _sha256(report), _sha256(markdown)
            report_payload = self._validate_report(
                report, markdown, task_id, version_id, parent_version_id,
                expected_parent_sha256, docx_hash, preview_artifact, references,
            )
            pdf_hash = self._validate_preview(pdf, preview_artifact, docx_hash)
            preview_metadata = stage / "preview-artifact.json"
            preview_metadata.write_text(
                json.dumps(asdict(preview_artifact), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            preview_metadata_hash = _sha256(preview_metadata)
            fingerprint = _sha256_bytes(json.dumps({
                "parent": parent_version_id, "parent_hash": expected_parent_sha256,
                "docx": docx_hash, "report": report_hash, "markdown": markdown_hash,
                "pdf": pdf_hash, "preview": asdict(preview_artifact),
                "references": asdict(references),
            }, sort_keys=True).encode("utf-8"))
            base = f"tasks/{task_id}/versions/{version_id}"
            created_at = _utc_now()
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM versions WHERE task_id=? AND request_id=?",
                    (task_id, request_id),
                ).fetchone()
                if existing is not None:
                    if (existing["request_fingerprint"] != fingerprint or
                            existing["version_id"] != version_id):
                        raise VersionStoreError("blocked_conflict", "Request ID was used for different output.")
                    return self._row_to_record(existing)
                task = connection.execute(
                    "SELECT working_version_id FROM tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                parent = connection.execute(
                    "SELECT * FROM versions WHERE task_id=? AND version_id=? AND status='ready'",
                    (task_id, parent_version_id),
                ).fetchone()
                if task is None or parent is None:
                    raise VersionStoreError("stale_base_version", "Selected parent version is unavailable.")
                if (task["working_version_id"] != parent_version_id or
                        parent["docx_sha256"] != expected_parent_sha256):
                    raise VersionStoreError("stale_base_version", "Working version or parent hash changed.")
                if not self._matches_hash(parent["docx_path"], parent["docx_sha256"]):
                    raise VersionStoreError("validation_failed", "Parent DOCX artifact is missing or changed.")
                if docx_hash != parent["docx_sha256"] and not report_payload["changes_this_round"]:
                    raise VersionStoreError("validation_failed", "Changed DOCX has no verified report changes.")
                if docx_hash == parent["docx_sha256"] and report_payload["changes_this_round"]:
                    raise VersionStoreError("validation_failed", "Report claims changes absent from DOCX bytes.")
                self._validate_report_lineage(parent, report_payload)
                output_count = connection.execute(
                    "SELECT COUNT(*) FROM versions WHERE task_id=? AND kind='output'",
                    (task_id,),
                ).fetchone()[0]
                if output_count and docx_hash == parent["docx_sha256"]:
                    raise VersionStoreError("no_document_change", "Decision did not change the DOCX.")
                sequence = connection.execute(
                    "SELECT MAX(sequence) FROM versions WHERE task_id=?", (task_id,)
                ).fetchone()[0] + 1
                if final_dir.exists() or not version_root.is_dir():
                    raise VersionStoreError("validation_failed", "Version target is unavailable.")
                if (version_root.is_symlink() or
                        (hasattr(version_root, "is_junction") and version_root.is_junction()) or
                        version_root.resolve().parent != (self.tasks_dir / task_id).resolve() or
                        (self.tasks_dir / task_id).resolve().parent != self.tasks_dir):
                    raise VersionStoreError("validation_failed", "Version target is redirected.")
                stage.rename(final_dir)
                published = True
                connection.execute("""
                    INSERT INTO versions (
                        version_id, task_id, parent_version_id, sequence, kind, status,
                        docx_path, docx_sha256, report_json_path, report_json_sha256,
                        report_markdown_path, report_markdown_sha256,
                        preview_path, preview_sha256,
                        preview_metadata_path, preview_metadata_sha256, preview_artifact_id,
                        renderer_id, renderer_version, references_json,
                        request_id, request_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, 'output', 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    version_id, task_id, parent_version_id, sequence,
                    f"{base}/document.docx", docx_hash,
                    f"{base}/report.json", report_hash,
                    f"{base}/report.md", markdown_hash,
                    f"{base}/{preview_artifact.pdf_relative_path}", pdf_hash,
                    f"{base}/preview-artifact.json", preview_metadata_hash,
                    preview_artifact.artifact_id, preview_artifact.renderer_id,
                    preview_artifact.renderer_version, references_json,
                    request_id, fingerprint, created_at,
                ))
                connection.execute(
                    "UPDATE tasks SET working_version_id=? WHERE task_id=?",
                    (version_id, task_id),
                )
            committed = True
            return self.get_version(task_id, version_id)
        except BaseException:
            if published and not committed:
                _safe_remove_directory(final_dir, version_root, self.root)
            raise
        finally:
            _safe_remove_directory(stage, self.staging_dir, self.root)

    @staticmethod
    def _validate_report(
        report: Path, markdown: Path, task_id: str, version_id: str,
        parent_version_id: str, parent_hash: str, docx_hash: str,
        preview_artifact: PreviewArtifact, references: VersionReferences,
    ) -> dict:
        if (not 0 < report.stat().st_size <= _MAX_REPORT_BYTES or
                not 0 < markdown.stat().st_size <= _MAX_REPORT_BYTES):
            raise VersionStoreError("validation_failed", "Version report is empty or too large.")
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            markdown_text = markdown.read_text(encoding="utf-8")
        except (ValueError, UnicodeError) as error:
            raise VersionStoreError("validation_failed", "Version report cannot be read.") from error
        try:
            validate_report(payload)
            expected_markdown = render_markdown(payload)
        except ReportError as error:
            raise VersionStoreError("validation_failed", str(error)) from error
        if markdown_text != expected_markdown:
            raise VersionStoreError("validation_failed", "Markdown report differs from JSON facts.")
        if any(payload.get(key) != value for key, value in (
            ("task_id", task_id), ("version_id", version_id),
            ("parent_version_id", parent_version_id),
            ("output_docx_sha256", docx_hash),
        )):
            raise VersionStoreError("validation_failed", "Version report does not match its DOCX.")
        expected_input = {
            "source_docx_sha256": parent_hash,
            "brief_version_id": references.brief_version_id,
            "rules_snapshot_id": references.rules_snapshot_id,
            "edit_plan_id": references.edit_plan_id,
            "template_version_id": references.template_version_id,
            "decision_version_id": references.decision_version_id,
        }
        expected_preview = {
            "artifact_id": preview_artifact.artifact_id,
            "renderer_id": preview_artifact.renderer_id,
            "renderer_version": preview_artifact.renderer_version,
            "font_fingerprint": references.font_fingerprint,
        }
        if payload["input"] != expected_input or payload["preview"] != expected_preview:
            raise VersionStoreError("validation_failed", "Report references do not match the version.")
        return payload

    def _validate_report_lineage(self, parent: sqlite3.Row, report: dict) -> None:
        if parent["kind"] == "original":
            if report["changes_cumulative"] != report["changes_this_round"]:
                raise VersionStoreError("validation_failed", "First report has inconsistent cumulative changes.")
            return
        if not self._matches_hash(parent["report_json_path"], parent["report_json_sha256"]):
            raise VersionStoreError("validation_failed", "Parent report is missing or changed.")
        try:
            parent_report = json.loads(
                self._artifact_path(parent["report_json_path"]).read_text(encoding="utf-8")
            )
            validate_report(parent_report)
        except (ValueError, UnicodeError, ReportError) as error:
            raise VersionStoreError("validation_failed", "Parent report cannot be validated.") from error
        previous = parent_report["changes_cumulative"]
        current = report["changes_cumulative"]
        if current[:len(previous)] != previous or current[len(previous):] != report["changes_this_round"]:
            raise VersionStoreError("validation_failed", "Cumulative changes do not extend the parent report.")
        if report["decisions"][:len(parent_report["decisions"])] != parent_report["decisions"]:
            raise VersionStoreError("validation_failed", "Report dropped a parent decision.")

    @staticmethod
    def _validate_preview(pdf: Path, artifact: PreviewArtifact, docx_hash: str) -> str:
        if (not 0 < pdf.stat().st_size <= _MAX_PDF_BYTES or
                artifact.source_sha256 != docx_hash or
                artifact.page_count < 1 or artifact.selectable_text_chars < 1):
            raise VersionStoreError("render_failed", "Preview does not match the candidate DOCX.")
        pdf_hash = _sha256(pdf)
        if pdf_hash != artifact.pdf_sha256:
            raise VersionStoreError("render_failed", "Preview PDF hash changed.")
        try:
            with pdf.open("rb") as stream:
                reader = PdfReader(stream, strict=True)
                page_count = len(reader.pages)
                text_chars = sum(len(page.extract_text() or "") for page in reader.pages)
        except (PdfReadError, OSError, ValueError) as error:
            raise VersionStoreError("render_failed", "Preview PDF cannot be read.") from error
        if page_count != artifact.page_count or text_chars != artifact.selectable_text_chars:
            raise VersionStoreError("render_failed", "Preview PDF text or page count changed.")
        return pdf_hash

    def get_version(self, task_id: str, version_id: str) -> VersionRecord:
        _require_id(task_id, "task")
        _require_id(version_id, "version")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM versions WHERE task_id=? AND version_id=?",
                (task_id, version_id),
            ).fetchone()
        if row is None:
            raise VersionStoreError("stale_base_version", "Version is unavailable.")
        return self._row_to_record(row)

    def list_versions(self, task_id: str) -> list[VersionRecord]:
        _require_id(task_id, "task")
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM versions WHERE task_id=? ORDER BY sequence", (task_id,)
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def working_version_id(self, task_id: str) -> str:
        _require_id(task_id, "task")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT working_version_id FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise VersionStoreError("stale_base_version", "Task is unavailable.")
        return row[0]

    def select_working_version(self, task_id: str, version_id: str) -> None:
        _require_id(task_id, "task")
        _require_id(version_id, "version")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, docx_path, docx_sha256 FROM versions WHERE task_id=? AND version_id=?",
                (task_id, version_id),
            ).fetchone()
            if (row is None or row["status"] != "ready" or
                    not self._matches_hash(row["docx_path"], row["docx_sha256"])):
                raise VersionStoreError("stale_base_version", "Selected version is unavailable.")
            connection.execute(
                "UPDATE tasks SET working_version_id=? WHERE task_id=?", (version_id, task_id)
            )

    def record_decision(
        self, *, task_id: str, base_version_id: str, request_id: str,
        kind: str, payload: dict,
    ) -> DecisionRecord:
        """Append a user decision without creating or modifying a DOCX version."""
        for label, value in (("task", task_id), ("base version", base_version_id),
                             ("request", request_id)):
            _require_id(value, label)
        if kind not in {"answer", "skip", "defer", "consultation"} or not isinstance(payload, dict):
            raise VersionStoreError("needs_user_input", "Decision kind or payload is invalid.")
        try:
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      allow_nan=False)
        except (TypeError, ValueError) as error:
            raise VersionStoreError("needs_user_input", "Decision payload is not JSON data.") from error
        if len(payload_json.encode("utf-8")) > 64 * 1024:
            raise VersionStoreError("needs_user_input", "Decision payload is too large.")
        payload_hash = _sha256_bytes(payload_json.encode("utf-8"))
        with self._transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM decisions WHERE task_id=? AND request_id=?",
                (task_id, request_id),
            ).fetchone()
            if previous is not None:
                if (previous["base_version_id"] != base_version_id or
                        previous["kind"] != kind or
                        previous["payload_sha256"] != payload_hash):
                    raise VersionStoreError("blocked_conflict", "Request ID was used for another decision.")
                return self._row_to_decision(previous)
            task = connection.execute(
                "SELECT working_version_id FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            version = connection.execute(
                "SELECT status FROM versions WHERE task_id=? AND version_id=?",
                (task_id, base_version_id),
            ).fetchone()
            if (task is None or version is None or version["status"] != "ready" or
                    task["working_version_id"] != base_version_id):
                raise VersionStoreError("stale_base_version", "Decision base version is no longer active.")
            decision_id = new_id()
            created_at = _utc_now()
            connection.execute("""
                INSERT INTO decisions (
                    decision_id, task_id, base_version_id, request_id, kind,
                    payload_json, payload_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (decision_id, task_id, base_version_id, request_id, kind,
                  payload_json, payload_hash, created_at))
        return DecisionRecord(decision_id, task_id, base_version_id, request_id,
                              kind, json.loads(payload_json), created_at)

    def list_decisions(self, task_id: str) -> list[DecisionRecord]:
        _require_id(task_id, "task")
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE task_id=? ORDER BY rowid", (task_id,)
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            decision_id=row["decision_id"], task_id=row["task_id"],
            base_version_id=row["base_version_id"], request_id=row["request_id"],
            kind=row["kind"], payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )

    def artifact_path(self, task_id: str, version_id: str, kind: str) -> Path:
        columns = {
            "docx": ("docx_path", "docx_sha256"),
            "report_json": ("report_json_path", "report_json_sha256"),
            "report_markdown": ("report_markdown_path", "report_markdown_sha256"),
            "preview": ("preview_path", "preview_sha256"),
            "preview_metadata": ("preview_metadata_path", "preview_metadata_sha256"),
        }
        if kind not in columns:
            raise VersionStoreError("validation_failed", "Artifact kind is not registered.")
        _require_id(task_id, "task")
        _require_id(version_id, "version")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM versions WHERE task_id=? AND version_id=? AND status='ready'",
                (task_id, version_id),
            ).fetchone()
        if row is None:
            raise VersionStoreError("validation_failed", "Ready version is unavailable.")
        path_column, hash_column = columns[kind]
        if not row[path_column] or not self._matches_hash(row[path_column], row[hash_column]):
            raise VersionStoreError("validation_failed", "Version artifact is missing or changed.")
        return self._artifact_path(row[path_column])

    def _matches_hash(self, relative_path: str, expected_hash: str) -> bool:
        path = self._artifact_path(relative_path)
        return path.is_file() and _sha256(path) == expected_hash

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> VersionRecord:
        references = (VersionReferences(**json.loads(row["references_json"]))
                      if row["references_json"] else None)
        return VersionRecord(
            task_id=row["task_id"], version_id=row["version_id"],
            parent_version_id=row["parent_version_id"], sequence=row["sequence"],
            kind=row["kind"], status=row["status"], docx_sha256=row["docx_sha256"],
            docx_relative_path=row["docx_path"],
            report_json_relative_path=row["report_json_path"],
            report_markdown_relative_path=row["report_markdown_path"],
            preview_relative_path=row["preview_path"],
            preview_metadata_relative_path=row["preview_metadata_path"],
            preview_artifact_id=row["preview_artifact_id"],
            renderer_id=row["renderer_id"], renderer_version=row["renderer_version"],
            references=references, created_at=row["created_at"],
        )

    def recover(self) -> None:
        """Remove unpublished stage/orphan directories and mark broken rows unusable."""
        for stage in self.staging_dir.iterdir():
            if _ID.fullmatch(stage.name):
                _safe_remove_directory(stage, self.staging_dir, self.root)
        with self._transaction() as connection:
            tasks = {row[0] for row in connection.execute("SELECT task_id FROM tasks")}
            versions = {row[0] for row in connection.execute("SELECT version_id FROM versions")}
            for task_dir in self.tasks_dir.iterdir():
                if not _ID.fullmatch(task_dir.name):
                    continue
                if task_dir.name not in tasks:
                    _safe_remove_directory(task_dir, self.tasks_dir, self.root)
                    continue
                if (_redirected(task_dir, self.tasks_dir) or
                        task_dir.resolve().parent != self.tasks_dir):
                    raise VersionStoreError("validation_failed", "Task directory is redirected.")
                version_dir = task_dir / "versions"
                if (not version_dir.is_dir() or
                        _redirected(version_dir, task_dir) or
                        version_dir.resolve().parent != task_dir.resolve()):
                    continue
                for child in version_dir.iterdir():
                    if _ID.fullmatch(child.name) and child.name not in versions:
                        _safe_remove_directory(child, version_dir, self.root)
            for row in connection.execute("SELECT * FROM versions WHERE status='ready'").fetchall():
                required = [(row["docx_path"], row["docx_sha256"])]
                if row["kind"] == "output":
                    required.extend((row[path], row[digest]) for path, digest in (
                        ("report_json_path", "report_json_sha256"),
                        ("report_markdown_path", "report_markdown_sha256"),
                        ("preview_path", "preview_sha256"),
                        ("preview_metadata_path", "preview_metadata_sha256"),
                    ))
                if any(not path or not digest or not self._recoverable_hash_match(path, digest)
                       for path, digest in required):
                    connection.execute(
                        "UPDATE versions SET status='validation_failed' WHERE version_id=?",
                        (row["version_id"],),
                    )

    def _recoverable_hash_match(self, relative_path: str, expected_hash: str) -> bool:
        try:
            return self._matches_hash(relative_path, expected_hash)
        except (OSError, VersionStoreError):
            return False


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
