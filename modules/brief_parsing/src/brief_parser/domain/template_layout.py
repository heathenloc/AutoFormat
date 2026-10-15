"""Read-only template observations; no observation is an executable rule."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from brief_parser.domain.base import Identifier, Sha256Hex, StrictModel


class TemplateLocation(StrictModel):
    part: str
    xpath: str
    section: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    run: int | None = None


class TemplatePropertyOrigin(StrictModel):
    part: str
    xpath: str
    layer: Literal[
        "section", "direct", "paragraph_style", "character_style", "table_style",
        "document_default", "theme",
    ]
    style_id: str | None = None
    raw_value: str
    node_sha256: Sha256Hex


class TemplateObservation(StrictModel):
    observation_id: Identifier
    source_id: Identifier
    source_sha256: Sha256Hex
    source_kind: Literal["template_observation"] = "template_observation"
    status: Literal["pending_confirmation"] = "pending_confirmation"
    semantic_role: Identifier
    role_basis: str
    region: Literal["template_candidate", "context_only", "uncertain"]
    property_id: Identifier
    character_scope: Identifier = "all"
    value: JsonValue
    unit: str | None = None
    resolution: Literal["resolved", "unresolved"]
    reason_codes: list[Identifier] = Field(default_factory=list)
    location: TemplateLocation
    origins: Annotated[list[TemplatePropertyOrigin], Field(min_length=1)]
    text_excerpt: Annotated[str, Field(max_length=120)] = ""

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.resolution == "resolved" and self.value is None:
            raise ValueError("resolved template observation needs a value")
        if self.resolution == "unresolved" and not self.reason_codes:
            raise ValueError("unresolved template observation needs a reason")
        return self


class TemplateSourceProfile(StrictModel):
    source_id: Identifier
    sha256: Sha256Hex
    kind: Literal["docx", "pdf", "txt", "text"]
    classification: Literal["template_candidate", "instruction_document", "uncertain", "not_available"]
    signal_codes: list[Identifier]


class TemplateDiagnostic(StrictModel):
    source_id: Identifier
    code: Identifier
    message: str
    location: TemplateLocation | None = None


class TemplatePropertyGroup(StrictModel):
    group_id: Identifier
    category: Identifier
    semantic_role: Identifier
    property_id: Identifier
    character_scope: Identifier
    status: Literal[
        "covered_by_explicit_rule", "source_mismatch", "blocked_by_pending_rule",
        "inconsistent_observations", "needs_template_confirmation", "unresolved_observation",
    ]
    observation_ids: Annotated[list[Identifier], Field(min_length=1)]
    explicit_rule_ids: list[Identifier]
    values: list[JsonValue]
    unit: str | None
    reason: str
    next_action: str


class TemplateLayoutReport(StrictModel):
    schema_version: Literal["academic-template-layout/1.0", "academic-template-layout/1.1"] = "academic-template-layout/1.1"
    reader_version: Literal["docx-template-layout/1.0", "docx-template-layout/1.1"] = "docx-template-layout/1.1"
    source_artifact_id: Identifier
    source_artifact_version: Annotated[int, Field(gt=0)]
    source_profiles: list[TemplateSourceProfile]
    observations: list[TemplateObservation]
    groups: list[TemplatePropertyGroup]
    diagnostics: list[TemplateDiagnostic]
    scope_note: str = "仅读取 Brief 的逻辑版式；观察值需确认后才能成为规则，不从论文原稿推导学校要求。"

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if self.schema_version.rsplit("/", 1)[-1] != self.reader_version.rsplit("/", 1)[-1]:
            raise ValueError("template reader and report versions differ")
        profiles = {profile.source_id: profile for profile in self.source_profiles}
        if len(profiles) != len(self.source_profiles):
            raise ValueError("template report repeats a source")
        observations = {item.observation_id: item for item in self.observations}
        if len(observations) != len(self.observations):
            raise ValueError("template report repeats an observation")
        for item in self.observations:
            if item.source_id not in profiles or item.source_sha256 != profiles[item.source_id].sha256:
                raise ValueError("template observation differs from source profile")
        if any(item.source_id not in profiles for item in self.diagnostics):
            raise ValueError("template diagnostic references another source")
        for group in self.groups:
            if not set(group.observation_ids) <= set(observations):
                raise ValueError("template group references unknown observations")
        if len({group.group_id for group in self.groups}) != len(self.groups):
            raise ValueError("template report repeats a group")
        return self
