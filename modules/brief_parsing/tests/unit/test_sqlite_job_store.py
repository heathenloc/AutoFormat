from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from brief_parser.adapters.sqlite_job_store import SQLiteJobStore
from brief_parser.domain.enums import Readiness
from brief_parser.domain.jobs import JobStatus, ParseJobParameters, ParseJobRecord
from brief_parser.errors import BriefParserError, ErrorCode


def _record(
    root: Path,
    *,
    fingerprint: str = "a" * 64,
    idempotency_key: str | None = "idem-1",
    expires_delta: timedelta = timedelta(days=1),
) -> ParseJobRecord:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    return ParseJobRecord(
        job_id="job_12345678",
        request_id="req_12345678",
        request_fingerprint=fingerprint,
        idempotency_key=idempotency_key,
        status=JobStatus.QUEUED,
        parameters=ParseJobParameters(
            domain="advertising_brief",
            task_types=["write_ad_script"],
        ),
        upload_dir=str(root / "uploads" / "job_12345678"),
        artifact_dir=str(root / "artifacts" / "job_12345678"),
        created_at=now,
        updated_at=now,
        expires_at=now + expires_delta,
    )


def test_job_store_is_idempotent_and_recovers_non_terminal_jobs(tmp_path: Path) -> None:
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    record = _record(tmp_path)

    created, reused = store.create_or_get(record)
    replay, replayed = store.create_or_get(record)

    assert reused is False
    assert replayed is True
    assert replay == created
    assert store.recoverable() == [record]

    completed = store.update_status(
        record.job_id,
        JobStatus.COMPLETED,
        readiness=Readiness.COMPLETE,
        updated_at=record.created_at + timedelta(minutes=1),
    )
    assert completed.result_readiness == "complete"
    assert store.recoverable() == []


def test_job_store_rejects_idempotency_key_reuse_for_another_request(
    tmp_path: Path,
) -> None:
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    store.create_or_get(_record(tmp_path))

    with pytest.raises(BriefParserError) as error:
        store.create_or_get(_record(tmp_path, fingerprint="b" * 64))

    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


def test_job_store_lists_expired_records(tmp_path: Path) -> None:
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    record = _record(tmp_path, idempotency_key=None, expires_delta=timedelta(hours=1))
    store.create_or_get(record)

    expired = store.expired(now=record.created_at + timedelta(hours=2))

    assert expired == [record]
