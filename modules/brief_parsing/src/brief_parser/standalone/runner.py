"""In-process standalone job execution backed by durable SQLite metadata."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from brief_parser.adapters.artifact_store import ArtifactDirectoryStore
from brief_parser.adapters.local_storage import StandaloneStorage
from brief_parser.adapters.sqlite_job_store import SQLiteJobStore
from brief_parser.application.service import BriefParserService, ParseServiceRequest
from brief_parser.domain.bundle import ParseBundle
from brief_parser.domain.jobs import TERMINAL_JOB_STATUSES, JobStatus
from brief_parser.errors import BriefParserError, ErrorCode


class StandaloneJobRunner:
    def __init__(
        self,
        service: BriefParserService,
        store: SQLiteJobStore,
        storage: StandaloneStorage,
        *,
        timeout_seconds: int,
        concurrency: int = 2,
        artifact_store: ArtifactDirectoryStore | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self._service = service
        self._store = store
        self._storage = storage
        self._timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._artifacts = artifact_store or ArtifactDirectoryStore()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, job_id: str) -> None:
        record = self._store.get(job_id)
        if record.status in TERMINAL_JOB_STATUSES:
            return
        current = self._tasks.get(job_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._run(job_id), name=f"brief-parser:{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))

    async def cancel(self, job_id: str) -> bool:
        record = self._store.get(job_id)
        if record.status in TERMINAL_JOB_STATUSES:
            return False
        task = self._tasks.get(job_id)
        if task is None:
            self._store.update_status(job_id, JobStatus.CANCELLED)
            return True
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return True

    def result(self, job_id: str) -> ParseBundle:
        record = self._store.get(job_id)
        if record.status != JobStatus.COMPLETED:
            raise BriefParserError(
                ErrorCode.JOB_NOT_READY,
                "Parse Job 尚未完成。",
                retryable=record.status not in TERMINAL_JOB_STATUSES,
                details={"status": record.status.value},
            )
        return self._artifacts.read(Path(record.artifact_dir))

    async def cleanup_expired(self) -> int:
        removed = 0
        for record in self._store.expired():
            if record.status not in TERMINAL_JOB_STATUSES:
                await self.cancel(record.job_id)
                record = self._store.get(record.job_id)
            self._storage.delete_job_data(
                upload_dir=Path(record.upload_dir),
                artifact_dir=Path(record.artifact_dir),
            )
            self._store.delete(record.job_id)
            removed += 1
        return removed

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        try:
            async with self._semaphore:
                record = self._store.update_status(
                    job_id,
                    JobStatus.VALIDATING_INPUT,
                )
                source_paths = tuple(sorted(Path(record.upload_dir).glob("source_*")))
                self._store.update_status(job_id, JobStatus.EXTRACTING_REQUIREMENTS)
                bundle = await self._service.parse_with_timeout(
                    ParseServiceRequest(
                        request_id=record.request_id,
                        domain_pack_id=record.parameters.domain,
                        domain_pack_version=record.parameters.domain_version,
                        requested_task_types=tuple(record.parameters.task_types),
                        source_paths=source_paths,
                        locale=record.parameters.locale,
                    ),
                    timeout_seconds=self._timeout_seconds,
                )
                self._store.update_status(job_id, JobStatus.COMPILING)
                self._artifacts.write(bundle, Path(record.artifact_dir))
                self._store.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    readiness=bundle.requirement_ir.readiness,
                )
        except asyncio.CancelledError:
            self._store.update_status(job_id, JobStatus.CANCELLED)
            raise
        except BriefParserError as error:
            self._fail(job_id, error)
        except Exception:
            self._fail(
                job_id,
                BriefParserError(
                    ErrorCode.INTERNAL_ERROR,
                    "Parse Job 执行失败。",
                    retryable=False,
                ),
            )

    def _fail(self, job_id: str, error: BriefParserError) -> None:
        response = error.to_response(trace_id=f"trace_{job_id.removeprefix('job_')}")
        self._store.update_status(
            job_id,
            JobStatus.FAILED,
            error_json=response.model_dump_json(),
        )
