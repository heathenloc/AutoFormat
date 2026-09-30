"""Canonical Requirement IR v1 contract."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from brief_parser.domain.base import (
    Identifier,
    Locale,
    RawTextModel,
    SemanticVersion,
    Sha256Hex,
    StrictModel,
)
from brief_parser.domain.enums import (
    DownstreamPolicy,
    EvidenceMatchStatus,
    Modality,
    Operator,
    Priority,
    Readiness,
    Severity,
    VerificationStatus,
)

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class DomainPackRef(StrictModel):
    id: Identifier
    version: SemanticVersion


class PipelineInfo(StrictModel):
    version: SemanticVersion
    parser_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_configs: dict[str, JsonValue] = Field(default_factory=dict)


class SourceManifest(StrictModel):
    source_id: Identifier
    client_source_id: Identifier
    kind: Literal["text", "txt", "docx", "pdf"]
    filename: str | None = None
    media_type: str
    byte_size: NonNegativeInt
    sha256: Sha256Hex
    language_hints: list[Locale] = Field(default_factory=list)
    parser_id: Identifier
    parser_version: SemanticVersion
    extraction_status: Literal["complete", "incomplete", "failed"]
    warnings: list[str] = Field(default_factory=list)


class SourceLocator(StrictModel):
    page: PositiveInt | None = None
    paragraph: NonNegativeInt | None = None
    table: NonNegativeInt | None = None
    section_path: list[str] = Field(default_factory=list)


class EvidenceReference(RawTextModel):
    evidence_id: Identifier
    source_id: Identifier
    block_id: Identifier
    start: NonNegativeInt
    end: PositiveInt
    index_basis: Literal["unicode_code_point"] = "unicode_code_point"
    quote: Annotated[str, Field(min_length=1)]
    quote_sha256: Sha256Hex
    locator: SourceLocator
    match_status: EvidenceMatchStatus

    @model_validator(mode="after")
    def validate_span_and_hash(self) -> Self:
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        digest = sha256(self.quote.encode("utf-8")).hexdigest()
        if digest != self.quote_sha256:
            raise ValueError("quote_sha256 does not match quote")
        return self


class EvidenceBackedItem(StrictModel):
    id: Identifier
    label: Annotated[str, Field(min_length=1)]
    value: JsonValue
    verification_status: VerificationStatus
    verification_basis: list[str] = Field(default_factory=list)
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    origin: Literal["source", "user_revision"] = "source"


class ReferenceItem(EvidenceBackedItem):
    relation: Literal["inspiration", "may_emulate", "must_not_copy", "context"] = "context"


class RequirementValue(StrictModel):
    type: Identifier
    amount: JsonValue
    unit: str | None = None


class RequirementScope(StrictModel):
    applies_to: list[Identifier] = Field(default_factory=list)
    excludes: list[Identifier] = Field(default_factory=list)


class RequirementCondition(StrictModel):
    expression: Annotated[str, Field(min_length=1)]
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]


class Requirement(StrictModel):
    id: Identifier
    semantic_key: Identifier
    category: Identifier
    custom_category: str | None = None
    label: Annotated[str, Field(min_length=1)]
    subject: Identifier
    modality: Modality
    operator: Operator
    value: RequirementValue
    scope: RequirementScope
    condition: RequirementCondition | None = None
    priority: Priority
    machine_checkability: Identifier
    verification_status: VerificationStatus
    verification_basis: list[str] = Field(default_factory=list)
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    origin: Literal["source", "user_revision"] = "source"
    downstream_policy: DownstreamPolicy


class Conflict(StrictModel):
    id: Identifier
    topic: Identifier
    severity: Severity
    items: Annotated[list[Identifier], Field(min_length=2)]
    reason_code: Identifier
    resolution: str | None = None
    downstream_policy: DownstreamPolicy


class UnresolvedItem(StrictModel):
    id: Identifier
    topic: Identifier
    description: Annotated[str, Field(min_length=1)]
    severity: Severity
    reason_code: Identifier
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    downstream_policy: Literal["do_not_assume", "block"]


class UnclassifiedContent(StrictModel):
    id: Identifier
    description: Annotated[str, Field(min_length=1)]
    evidence_refs: Annotated[list[Identifier], Field(min_length=1)]
    reason_code: Identifier


class QualityMetrics(StrictModel):
    source_extraction_quality: dict[str, Literal["complete", "degraded", "failed"]] = Field(
        default_factory=dict
    )
    clause_count: NonNegativeInt = 0
    classified_clause_count: NonNegativeInt = 0
    unclassified_clause_count: NonNegativeInt = 0
    coverage_ratio: Ratio = 0.0
    evidence_validity_ratio: Ratio = 0.0
    numeric_validation_ratio: Ratio = 0.0
    conflict_count: NonNegativeInt = 0
    unresolved_count: NonNegativeInt = 0
    blocker_count: NonNegativeInt = 0
    provider_call_count: NonNegativeInt = 0
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    latency_ms: NonNegativeInt = 0
    readiness_reason_codes: list[str] = Field(default_factory=list)


class Extension(StrictModel):
    namespace: Identifier
    version: SemanticVersion
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class RequirementIR(StrictModel):
    schema_version: Literal["requirement-ir/1.0"] = "requirement-ir/1.0"
    artifact_id: Identifier
    artifact_version: PositiveInt
    request_id: Identifier
    created_at: datetime
    readiness: Readiness
    locale: Locale = "zh-CN"
    domain_pack: DomainPackRef
    pipeline: PipelineInfo
    source_manifest: Annotated[list[SourceManifest], Field(min_length=1)]
    facts: list[EvidenceBackedItem] = Field(default_factory=list)
    objectives: list[EvidenceBackedItem] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    references: list[ReferenceItem] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)
    unclassified_content: list[UnclassifiedContent] = Field(default_factory=list)
    evidence_index: dict[Identifier, EvidenceReference] = Field(default_factory=dict)
    quality: QualityMetrics
    extensions: list[Extension] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")

        source_ids = {source.source_id for source in self.source_manifest}
        evidence_ids = set(self.evidence_index)
        for key, evidence in self.evidence_index.items():
            if key != evidence.evidence_id:
                raise ValueError("evidence_index key must equal evidence_id")
            if evidence.source_id not in source_ids:
                raise ValueError(f"evidence {key!r} references an unknown source")

        def validate_evidence_links(item_id: str, item_evidence_refs: list[str]) -> None:
            missing = set(item_evidence_refs) - evidence_ids
            if missing:
                raise ValueError(
                    f"item {item_id!r} references unknown evidence: {sorted(missing)}"
                )

        for items in (
            self.facts,
            self.objectives,
            self.references,
            self.unresolved_items,
            self.unclassified_content,
        ):
            for item in items:
                validate_evidence_links(item.id, item.evidence_refs)
        for requirement in self.requirements:
            validate_evidence_links(requirement.id, requirement.evidence_refs)
            if requirement.condition is not None:
                missing_condition = set(requirement.condition.evidence_refs) - evidence_ids
                if missing_condition:
                    raise ValueError(
                        f"item {requirement.id!r} condition references unknown evidence: "
                        f"{sorted(missing_condition)}"
                    )

        requirement_ids = {requirement.id for requirement in self.requirements}
        for conflict in self.conflicts:
            missing_items = set(conflict.items) - requirement_ids
            if missing_items:
                raise ValueError(
                    f"conflict {conflict.id!r} references unknown requirements: "
                    f"{sorted(missing_items)}"
                )
        return self
