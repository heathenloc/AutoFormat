"""Standalone HTTP API request and response contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import Readiness
from brief_parser.domain.jobs import JobStatus, ParseJobParameters
from brief_parser.errors import ErrorResponse


class CreateParseJobResponse(StrictModel):
    job_id: Identifier
    status: JobStatus
    status_url: str
    result_url: str


class ParseJobStatusResponse(StrictModel):
    job_id: Identifier
    status: JobStatus
    readiness: Readiness | None = None
    error: ErrorResponse | None = None


class HealthResponse(StrictModel):
    status: Literal["ok", "ready", "not_ready"]


class VersionResponse(StrictModel):
    package: str
    pipeline: str
    parse_bundle: str
    parse_manifest: str
    requirement_ir: str
    execution_brief: str
    domain_pack: str


class MultipartParseJobRequest(ParseJobParameters):
    task_types: list[Identifier] = Field(min_length=1, max_length=10)
