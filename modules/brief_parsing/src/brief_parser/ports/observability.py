"""Safe, host-neutral observability boundary for completed parse pipelines."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import Readiness
from brief_parser.domain.pipeline import ProviderCallRecord, StageRecord


class PipelineObservation(StrictModel):
    """Allowlisted operational metadata; source content cannot enter this model."""

    trace_id: Identifier
    request_id: Identifier
    duration_ms: int = Field(ge=0)
    readiness: Readiness
    clause_count: int = Field(ge=0)
    stages: list[StageRecord] = Field(default_factory=list)
    provider_calls: list[ProviderCallRecord] = Field(default_factory=list)
    readiness_reason_codes: list[str] = Field(default_factory=list)


class ObservationSink(Protocol):
    def record_pipeline(self, observation: PipelineObservation) -> None:
        """Record safe operational metadata without source or prompt content."""
