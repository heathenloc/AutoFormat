"""SQLite metadata store for standalone jobs only."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brief_parser.domain.enums import Readiness
from brief_parser.domain.jobs import (
    TERMINAL_JOB_STATUSES,
    JobStatus,
    ParseJobParameters,
    ParseJobRecord,
)
from brief_parser.errors import BriefParserError, ErrorCode


class SQLiteJobStore:
    def __init__(self, path: Path) -> None:
        self._path = path.resolve()

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_jobs (
                    job_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    upload_dir TEXT NOT NULL,
                    artifact_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    result_readiness TEXT,
                    error_json TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_parse_jobs_expires_at ON parse_jobs(expires_at)"
            )

    def create_or_get(self, record: ParseJobRecord) -> tuple[ParseJobRecord, bool]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if record.idempotency_key is not None:
                row = connection.execute(
                    "SELECT * FROM parse_jobs WHERE idempotency_key = ?",
                    (record.idempotency_key,),
                ).fetchone()
                if row is not None:
                    existing = self._record(row)
                    if existing.request_fingerprint != record.request_fingerprint:
                        raise BriefParserError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "相同 Idempotency-Key 对应了不同请求。",
                        )
                    return existing, True
            connection.execute(
                """
                INSERT INTO parse_jobs (
                    job_id, request_id, request_fingerprint, idempotency_key,
                    status, parameters_json, upload_dir, artifact_dir,
                    created_at, updated_at, expires_at, result_readiness, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(record),
            )
        return record, False

    def get(self, job_id: str) -> ParseJobRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM parse_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise BriefParserError(ErrorCode.JOB_NOT_FOUND, "Parse Job 不存在。")
        return self._record(row)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        readiness: Readiness | None = None,
        error_json: str | None = None,
        updated_at: datetime | None = None,
    ) -> ParseJobRecord:
        current = self.get(job_id)
        if current.status in TERMINAL_JOB_STATUSES and current.status != status:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "终态 Parse Job 不能继续转换状态。",
            )
        changed_at = updated_at or datetime.now(UTC)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE parse_jobs
                SET status = ?, updated_at = ?, result_readiness = ?, error_json = ?
                WHERE job_id = ?
                """,
                (
                    status.value,
                    changed_at.isoformat(),
                    None if readiness is None else readiness.value,
                    error_json,
                    job_id,
                ),
            )
        return self.get(job_id)

    def delete(self, job_id: str) -> ParseJobRecord:
        record = self.get(job_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM parse_jobs WHERE job_id = ?", (job_id,))
        return record

    def expired(self, *, now: datetime | None = None) -> list[ParseJobRecord]:
        current = now or datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM parse_jobs WHERE expires_at <= ? ORDER BY expires_at",
                (current.isoformat(),),
            ).fetchall()
        return [self._record(row) for row in rows]

    def recoverable(self) -> list[ParseJobRecord]:
        terminal = tuple(item.value for item in TERMINAL_JOB_STATUSES)
        placeholders = ", ".join("?" for _ in terminal)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM parse_jobs WHERE status NOT IN ({placeholders}) "
                "ORDER BY created_at",
                terminal,
            ).fetchall()
        return [self._record(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _values(record: ParseJobRecord) -> tuple[Any, ...]:
        return (
            record.job_id,
            record.request_id,
            record.request_fingerprint,
            record.idempotency_key,
            record.status.value,
            record.parameters.model_dump_json(),
            record.upload_dir,
            record.artifact_dir,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.expires_at.isoformat(),
            (None if record.result_readiness is None else record.result_readiness.value),
            record.error_json,
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> ParseJobRecord:
        parameters = ParseJobParameters.model_validate(json.loads(row["parameters_json"]))
        readiness_value = row["result_readiness"]
        return ParseJobRecord(
            job_id=row["job_id"],
            request_id=row["request_id"],
            request_fingerprint=row["request_fingerprint"],
            idempotency_key=row["idempotency_key"],
            status=JobStatus(row["status"]),
            parameters=parameters,
            upload_dir=row["upload_dir"],
            artifact_dir=row["artifact_dir"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            result_readiness=(None if readiness_value is None else Readiness(readiness_value)),
            error_json=row["error_json"],
        )
