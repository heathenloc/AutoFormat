"""Versioned academic formatting projection; never a DOCX edit manifest."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.requirement_ir import DomainPackRef, EvidenceReference


class AcademicTarget(StrictModel):
    object_kind: Identifier
    semantic_role: Identifier
    selector: Identifier


class AcademicValue(StrictModel):
    original_text: Annotated[str, Field(min_length=1)]
    normalized: JsonValue
    unit: str | None = None
    dictionary_version: Identifier


class AcademicFormatRule(StrictModel):
    schema_version: Literal["academic-format-rule/1.0"] = "academic-format-rule/1.0"
    rule_id: Identifier
    source_requirement_id: Identifier
    source_kind: Literal[
        "brief_explicit", "template_observation_confirmed", "user_feedback"
    ]
    source_artifact_id: Identifier
    source_version: Identifier
    evidence_refs: Annotated[list[EvidenceReference], Field(min_length=1)]
    target: AcademicTarget
    property_id: Identifier
    value: AcademicValue
    character_scope: Identifier = "all"
    condition: str | None = None
    requested_scope: Literal["selection", "paragraph", "same_kind", "document"]
    effective_scope: Literal["selection", "paragraph", "same_kind", "document"]
    status: Literal[
        "verified", "pending_conflict", "pending_condition", "check_only", "unsupported"
    ]
    reason: Annotated[str, Field(min_length=1)]
    decision_id: str | None = None
    resolution_ref: str | None = None

    @model_validator(mode="after")
    def require_decision_for_confirmed_non_brief_rule(self) -> Self:
        if (self.status == "verified" and self.source_kind != "brief_explicit"
                and not self.decision_id):
            raise ValueError("confirmed template or feedback rule needs a decision")
        return self


class AcademicFormatIssue(StrictModel):
    source_requirement_id: Identifier
    status: Literal[
        "needs_source_classification", "pending_conflict", "pending_condition",
        "evidence_unverified", "value_evidence_mismatch", "unsupported",
        "check_only", "parse_incomplete", "needs_value", "ambiguous_target",
    ]
    reason: Annotated[str, Field(min_length=1)]
    next_action: Annotated[str, Field(min_length=1)]
    evidence_ids: list[Identifier]
    target: AcademicTarget | None = None
    property_id: Identifier | None = None
    original_text: str | None = None


class AcademicFormatRuleSet(StrictModel):
    schema_version: Literal[
        "academic-format-rule-set/1.0", "academic-format-rule-set/1.1",
        "academic-format-rule-set/1.2",
    ] = "academic-format-rule-set/1.2"
    source_artifact_id: Identifier
    source_artifact_version: Annotated[int, Field(gt=0)]
    domain_pack: DomainPackRef
    compiler_version: Literal["1.0.0", "1.1.0", "1.2.0"] = "1.2.0"
    rules: list[AcademicFormatRule]
    issues: list[AcademicFormatIssue]

    @model_validator(mode="after")
    def validate_provenance_and_uniqueness(self) -> Self:
        rule_ids = [rule.rule_id for rule in self.rules]
        source_ids = [rule.source_requirement_id for rule in self.rules]
        issue_ids = [issue.source_requirement_id for issue in self.issues]
        if len(rule_ids) != len(set(rule_ids)) or len(source_ids + issue_ids) != len(
            set(source_ids + issue_ids)
        ):
            raise ValueError("academic projection repeats a rule or requirement")
        expected_version = f"{self.source_artifact_id}:v{self.source_artifact_version}"
        if any(
            rule.source_artifact_id != self.source_artifact_id
            or rule.source_version != expected_version
            for rule in self.rules
        ):
            raise ValueError("academic rule points to another source IR")
        return self
