"""Standalone FastAPI application with no Creator's Voice dependencies."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from brief_parser.adapters.local_storage import IncomingUpload, StandaloneStorage
from brief_parser.adapters.sqlite_job_store import SQLiteJobStore
from brief_parser.api.models import (
    CreateParseJobResponse,
    HealthResponse,
    MultipartParseJobRequest,
    ParseJobStatusResponse,
    VersionResponse,
)
from brief_parser.application.service import BriefParserService
from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.domain.bundle import ParseBundle
from brief_parser.domain.jobs import JobStatus, ParseJobRecord
from brief_parser.errors import BriefParserError, ErrorCode, ErrorResponse
from brief_parser.standalone.runner import StandaloneJobRunner
from brief_parser.version import (
    DOMAIN_PACK_SCHEMA_VERSION,
    EXECUTION_BRIEF_SCHEMA_VERSION,
    PARSE_BUNDLE_VERSION,
    PARSE_MANIFEST_SCHEMA_VERSION,
    PIPELINE_VERSION,
    REQUIREMENT_IR_SCHEMA_VERSION,
    __version__,
)

CLEANUP_INTERVAL_SECONDS = 3600


def create_app(
    settings: Settings | None = None,
    *,
    service: BriefParserService | None = None,
) -> FastAPI:
    configured = settings or Settings.from_env()
    if configured.mode != "standalone":
        raise ValueError("standalone API requires BRIEF_PARSER_MODE=standalone")

    storage = StandaloneStorage(
        configured.storage_dir,
        max_file_bytes=configured.max_file_bytes,
    )
    store = SQLiteJobStore(configured.sqlite_path)
    parser_service = service or build_service(configured)
    runner = StandaloneJobRunner(
        parser_service,
        store,
        storage,
        timeout_seconds=configured.job_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        storage.initialize()
        store.initialize()
        await runner.cleanup_expired()
        for record in store.recoverable():
            runner.schedule(record.job_id)
        cleanup_task = asyncio.create_task(_cleanup_loop(runner))
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
            await runner.shutdown()

    app = FastAPI(
        title="Brief Parser Standalone API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.ready = False
    app.state.store = store
    app.state.storage = storage
    app.state.runner = runner

    @app.exception_handler(BriefParserError)
    async def brief_parser_error_handler(
        request: Request,
        error: BriefParserError,
    ) -> JSONResponse:
        del request
        response = error.to_response(trace_id=f"trace_{uuid4().hex}")
        return JSONResponse(
            status_code=_status_code(error.code),
            content=response.model_dump(mode="json"),
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(
        request: Request,
        error: ValidationError,
    ) -> JSONResponse:
        del request
        safe_error = BriefParserError(
            ErrorCode.INVALID_REQUEST,
            "请求无法通过 Schema 校验。",
            details={"validation_error_count": error.error_count()},
        )
        response = safe_error.to_response(trace_id=f"trace_{uuid4().hex}")
        return JSONResponse(status_code=422, content=response.model_dump(mode="json"))

    @app.post("/v1/parse-jobs", response_model=CreateParseJobResponse, status_code=202)
    async def create_parse_job(
        request_json: Annotated[str, Form(alias="request")],
        sources: Annotated[list[UploadFile], File()],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateParseJobResponse:
        try:
            parameters = MultipartParseJobRequest.model_validate_json(request_json)
        except ValidationError as exc:
            raise exc
        if len(sources) > configured.max_sources:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "上传 Source 数量超过允许上限。",
                details={"max_sources": configured.max_sources},
            )
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 200:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "Idempotency-Key 长度无效。",
            )

        incoming: list[IncomingUpload] = []
        for source in sources:
            content = await source.read(configured.max_file_bytes + 1)
            await source.close()
            if len(content) > configured.max_file_bytes:
                raise BriefParserError(
                    ErrorCode.SOURCE_TOO_LARGE,
                    "上传文件超过允许的大小上限。",
                    details={"max_file_bytes": configured.max_file_bytes},
                )
            incoming.append(
                IncomingUpload(
                    filename=source.filename or "source.txt",
                    content=content,
                )
            )

        job_id = f"job_{uuid4().hex}"
        request_id = f"req_{uuid4().hex}"
        stored = storage.store_uploads(job_id, incoming)
        upload_dir = storage.upload_root / job_id
        artifact_dir = storage.artifact_root / job_id
        fingerprint = storage.fingerprint(
            stored,
            parameters_json=parameters.model_dump_json(),
        )
        now = datetime.now(UTC)
        record = ParseJobRecord(
            job_id=job_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            status=JobStatus.QUEUED,
            parameters=parameters,
            upload_dir=str(upload_dir),
            artifact_dir=str(artifact_dir),
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=configured.retention_days),
        )
        try:
            persisted, reused = store.create_or_get(record)
        except Exception:
            storage.delete_job_data(
                upload_dir=upload_dir,
                artifact_dir=artifact_dir,
            )
            raise
        if reused:
            storage.delete_job_data(
                upload_dir=upload_dir,
                artifact_dir=artifact_dir,
            )
        else:
            runner.schedule(persisted.job_id)
        return _created_response(persisted)

    @app.get("/v1/parse-jobs/{job_id}", response_model=ParseJobStatusResponse)
    async def get_parse_job(job_id: str) -> ParseJobStatusResponse:
        return _status_response(store.get(job_id))

    @app.get("/v1/parse-jobs/{job_id}/result", response_model=ParseBundle)
    async def get_parse_job_result(job_id: str) -> ParseBundle:
        return runner.result(job_id)

    @app.delete("/v1/parse-jobs/{job_id}", status_code=204)
    async def delete_parse_job(job_id: str) -> Response:
        record = store.get(job_id)
        await runner.cancel(job_id)
        storage.delete_job_data(
            upload_dir=Path(record.upload_dir),
            artifact_dir=Path(record.artifact_dir),
        )
        store.delete(job_id)
        return Response(status_code=204)

    @app.get("/health/live", response_model=HealthResponse)
    async def health_live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse)
    async def health_ready(request: Request) -> HealthResponse:
        if not bool(request.app.state.ready):
            return HealthResponse(status="not_ready")
        return HealthResponse(status="ready")

    @app.get("/version", response_model=VersionResponse)
    async def version() -> VersionResponse:
        return VersionResponse(
            package=__version__,
            pipeline=PIPELINE_VERSION,
            parse_bundle=PARSE_BUNDLE_VERSION,
            parse_manifest=PARSE_MANIFEST_SCHEMA_VERSION,
            requirement_ir=REQUIREMENT_IR_SCHEMA_VERSION,
            execution_brief=EXECUTION_BRIEF_SCHEMA_VERSION,
            domain_pack=DOMAIN_PACK_SCHEMA_VERSION,
        )

    return app


async def _cleanup_loop(runner: StandaloneJobRunner) -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        await runner.cleanup_expired()


def _created_response(record: ParseJobRecord) -> CreateParseJobResponse:
    return CreateParseJobResponse(
        job_id=record.job_id,
        status=record.status,
        status_url=f"/v1/parse-jobs/{record.job_id}",
        result_url=f"/v1/parse-jobs/{record.job_id}/result",
    )


def _status_response(record: ParseJobRecord) -> ParseJobStatusResponse:
    error = (
        None
        if record.error_json is None
        else ErrorResponse.model_validate(json.loads(record.error_json))
    )
    return ParseJobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        readiness=record.result_readiness,
        error=error,
    )


def _status_code(code: ErrorCode) -> int:
    if code == ErrorCode.JOB_NOT_FOUND:
        return 404
    if code in {ErrorCode.IDEMPOTENCY_CONFLICT, ErrorCode.JOB_NOT_READY}:
        return 409
    if code in {
        ErrorCode.SOURCE_TOO_LARGE,
        ErrorCode.SOURCE_TOO_MANY_PAGES,
        ErrorCode.SOURCE_UNSUPPORTED,
        ErrorCode.SOURCE_MIME_MISMATCH,
        ErrorCode.SOURCE_TEXT_ENCODING,
        ErrorCode.SOURCE_ARCHIVE_INVALID,
        ErrorCode.SOURCE_ARCHIVE_PATH_TRAVERSAL,
        ErrorCode.SOURCE_ARCHIVE_BOMB,
        ErrorCode.SOURCE_XML_UNSAFE,
        ErrorCode.SOURCE_MACRO_ENABLED,
        ErrorCode.SOURCE_ENCRYPTED,
        ErrorCode.SOURCE_PDF_INVALID,
        ErrorCode.SOURCE_SCANNED_PDF,
        ErrorCode.SOURCE_EXTRACTION_QUALITY,
    }:
        return 422
    if code == ErrorCode.PROVIDER_TRANSIENT:
        return 503
    if code == ErrorCode.INTERNAL_ERROR:
        return 500
    return 400
