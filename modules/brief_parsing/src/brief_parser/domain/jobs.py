"""Standalone job contracts kept separate from host application concepts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, Locale, Sha256Hex, StrictModel
from brief_parser.domain.enums import Readiness


class JobStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING_INPUT = "validating_input"
    EXTRACTING = "extracting"
    QUALITY_CHECKING = "quality_checking"
    SEGMENTING = "segmenting"
    EXTRACTING_REQUIREMENTS = "extracting_requirements"
    AUDITING_COVERAGE = "auditing_coverage"
    VALIDATING_REQUIREMENTS = "validating_requirements"
    RESOLVING = "resolving"
    COMPILING = "compiling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


class ParseJobParameters(StrictModel):
    domain: Identifier
    domain_version: str | None = None
    task_types: Annotated[list[Identifier], Field(min_length=1)]
    locale: Locale = "zh-CN"

    @model_validator(mode="after")
    def validate_unique_tasks(self) -> Self:
        if len(self.task_types) != len(set(self.task_types)):
            raise ValueError("task_types must be unique")
        return self


class ParseJobRecord(StrictModel):
    job_id: Identifier
    request_id: Identifier
    request_fingerprint: Sha256Hex
    idempotency_key: str | None = None
    status: JobStatus
    parameters: ParseJobParameters
    upload_dir: str
    artifact_dir: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    result_readiness: Readiness | None = None
    error_json: str | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        for value in (self.created_at, self.updated_at, self.expires_at):
            if value.utcoffset() is None:
                raise ValueError("job timestamps must include a timezone")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must follow created_at")
        if self.status == JobStatus.COMPLETED and self.result_readiness is None:
            raise ValueError("completed jobs require result_readiness")
        if self.status != JobStatus.COMPLETED and self.result_readiness is not None:
            raise ValueError("only completed jobs may have result_readiness")
        if self.status == JobStatus.FAILED and self.error_json is None:
            raise ValueError("failed jobs require error_json")
        return self
