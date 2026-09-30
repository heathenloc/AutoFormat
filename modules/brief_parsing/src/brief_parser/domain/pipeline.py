"""Pipeline manifest and completed Phase 4 result contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, Locale, SemanticVersion, Sha256Hex, StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.domain.requirement_ir import DomainPackRef, RequirementIR

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class PipelineSourceRecord(StrictModel):
    source_id: Identifier
    sha256: Sha256Hex
    parser_id: Identifier
    parser_version: SemanticVersion
    extraction_status: Literal["complete", "incomplete", "failed"]


class ProviderCallRecord(StrictModel):
    role: ModelRole
    provider_alias: Identifier
    model_id: Identifier
    provider_request_id: str | None
    completion_status: Literal["completed", "refused", "incomplete"]
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    latency_ms: NonNegativeInt
    retry_count: NonNegativeInt


class StageRecord(StrictModel):
    stage: Identifier
    status: Literal["completed", "skipped"]
    duration_ms: NonNegativeInt
    item_count: NonNegativeInt = 0
    reason_code: Identifier | None = None


class ParseManifest(StrictModel):
    schema_version: Literal["parse-manifest/1.0"] = "parse-manifest/1.0"
    request_id: Identifier
    request_fingerprint: Sha256Hex
    artifact_id: Identifier
    artifact_version: PositiveInt
    created_at: datetime
    locale: Locale
    pipeline_version: SemanticVersion
    domain_pack: DomainPackRef
    requested_task_types: Annotated[list[Identifier], Field(min_length=1)]
    prompt_versions: dict[str, str]
    model_routes: dict[str, str]
    sources: Annotated[list[PipelineSourceRecord], Field(min_length=1)]
    stages: list[StageRecord]
    provider_calls: list[ProviderCallRecord]
    readiness_reason_codes: list[str]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.created_at.utcoffset() is None:
            raise ValueError("manifest created_at must include a timezone")
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("manifest source ids must be unique")
        return self


class PipelineResult(StrictModel):
    requirement_ir: RequirementIR
    manifest: ParseManifest

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if self.requirement_ir.artifact_id != self.manifest.artifact_id:
            raise ValueError("manifest artifact_id does not match requirement IR")
        if self.requirement_ir.artifact_version != self.manifest.artifact_version:
            raise ValueError("manifest artifact_version does not match requirement IR")
        if self.requirement_ir.request_id != self.manifest.request_id:
            raise ValueError("manifest request_id does not match requirement IR")
        if self.requirement_ir.readiness.value not in {
            "complete",
            "usable_with_warnings",
            "incomplete",
        }:
            raise ValueError("requirement IR readiness is invalid")
        return self
