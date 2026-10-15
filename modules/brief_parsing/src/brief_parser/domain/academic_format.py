"""Versioned academic formatting projection; never a DOCX edit manifest."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator, model_serializer

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.requirement_ir import DomainPackRef, EvidenceReference
from brief_parser.domain.academic_semantics import (
    AcademicRuleSemantics, AcademicRuleRelation, AcademicRuleConflict, AcademicRuleFragment,
)


class AcademicTarget(StrictModel):
    object_kind: Identifier
    semantic_role: Identifier
    selector: Identifier


class AcademicValue(StrictModel):
    original_text: Annotated[str, Field(min_length=1)]
    normalized: JsonValue
    unit: str | None = None
    dictionary_version: Identifier


def finite_value(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_value(item) for item in value.values())
    if isinstance(value, list):
        return all(finite_value(item) for item in value)
    return True


class AcademicFormatRule(StrictModel):
    schema_version: Literal["academic-format-rule/1.0", "academic-format-rule/1.1"] = "academic-format-rule/1.0"
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
    semantics: AcademicRuleSemantics | None = None

    @model_serializer(mode="wrap")
    def preserve_rule_shape(self, handler):
        data = handler(self)
        if self.schema_version == "academic-format-rule/1.0":
            data.pop("semantics", None)
        return data

    @model_validator(mode="after")
    def require_decision_for_confirmed_non_brief_rule(self) -> Self:
        if (self.semantics is not None) != (self.schema_version == "academic-format-rule/1.1"):
            raise ValueError("typed semantics require academic rule 1.1")
        if self.semantics is not None:
            if not finite_value(self.value.normalized):
                raise ValueError("typed format values must be finite")
            if (self.property_id == "font.size" and isinstance(self.value.normalized, (int, float))
                    and self.value.normalized <= 0):
                raise ValueError("font size must be positive")
            condition = self.semantics.condition
            if self.condition != (condition.original_text if condition else None):
                raise ValueError("condition text differs from typed semantics")
            if self.status == "verified" and (condition or self.semantics.constraint.operator != "eq"):
                raise ValueError("conditional or non-equality rule cannot be globally verified")
            constraint = self.semantics.constraint
            expected = ({"min": constraint.lower, "max": constraint.upper} if constraint.operator == "between"
                        else {"min": constraint.lower} if constraint.operator == "gte"
                        else {"max": constraint.upper} if constraint.operator == "lte" else None)
            if expected is not None and self.value.normalized != expected:
                raise ValueError("normalized value differs from constraint bounds")
            from brief_parser.compilers.academic_scope import base_scope, intersection
            base = base_scope(self.target.semantic_role, self.property_id, self.character_scope)
            if intersection(base, self.semantics.scope) != self.semantics.scope:
                raise ValueError("typed scope exceeds declared object or character scope")
            if self.target.selector == "semantic_role" and self.semantics.scope != base:
                raise ValueError("filtered rule requires a scoped selector")
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


class AcademicCandidateReview(StrictModel):
    """Audit of a model Requirement; it grants no editing authority itself."""
    source_requirement_id: Identifier
    status: Literal["accepted", "covered", "rejected", "pending"]
    reason_code: Identifier
    reason: Annotated[str, Field(min_length=1)]
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    property_id: Identifier | None = None
    rule_ids: list[Identifier] = Field(default_factory=list)


class AcademicFormatRuleSet(StrictModel):
    schema_version: Literal[
        "academic-format-rule-set/1.0", "academic-format-rule-set/1.1",
        "academic-format-rule-set/1.2",
        "academic-format-rule-set/1.3",
        "academic-format-rule-set/1.4",
        "academic-format-rule-set/1.5",
    ] = "academic-format-rule-set/1.2"
    source_artifact_id: Identifier
    source_artifact_version: Annotated[int, Field(gt=0)]
    domain_pack: DomainPackRef
    compiler_version: Literal["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0"] = "1.2.0"
    rules: list[AcademicFormatRule]
    issues: list[AcademicFormatIssue]
    relations: list[AcademicRuleRelation] = Field(default_factory=list)
    conflicts: list[AcademicRuleConflict] = Field(default_factory=list)
    fragments: list[AcademicRuleFragment] = Field(default_factory=list)
    candidate_reviews: list[AcademicCandidateReview] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def preserve_ruleset_shape(self, handler):
        data = handler(self)
        if self.schema_version not in {"academic-format-rule-set/1.4", "academic-format-rule-set/1.5"}:
            for field in ("relations", "conflicts", "fragments"):
                data.pop(field, None)
        if self.schema_version != "academic-format-rule-set/1.5":
            data.pop("candidate_reviews", None)
        return data

    @model_validator(mode="after")
    def validate_provenance_and_uniqueness(self) -> Self:
        current = self.schema_version in {"academic-format-rule-set/1.4", "academic-format-rule-set/1.5"}
        if not current and (self.relations or self.conflicts or self.fragments):
            raise ValueError("scope analysis requires ruleset 1.4")
        if current:
            expected_compiler = "1.5.0" if self.schema_version.endswith("1.5") else "1.4.0"
            if self.compiler_version != expected_compiler or any(rule.semantics is None for rule in self.rules):
                raise ValueError("ruleset 1.4 requires typed rule semantics")
            from brief_parser.compilers.academic_scope import analyze_rules
            expected = analyze_rules(self.rules)
            if (self.relations, self.conflicts, self.fragments) != expected:
                raise ValueError("scope analysis differs from typed rules")
            for rule in self.rules:
                related = [item for item in self.conflicts if rule.rule_id in item.rule_ids]
                status = ("pending_conflict" if any(item.certainty == "definite" for item in related)
                          else "pending_condition" if related or rule.semantics.condition
                          else "check_only" if rule.semantics.constraint.operator != "eq" else "verified")
                if rule.status != status:
                    raise ValueError("rule status differs from scope analysis")
        if self.schema_version != "academic-format-rule-set/1.5" and self.candidate_reviews:
            raise ValueError("candidate review requires ruleset 1.5")
        reviews = self.candidate_reviews
        if len({item.source_requirement_id for item in reviews}) != len(reviews):
            raise ValueError("candidate review repeats a Requirement")
        for review in reviews:
            if not set(review.rule_ids) <= {rule.rule_id for rule in self.rules}:
                raise ValueError("candidate review references an unknown rule")
            if (review.status in {"accepted", "covered"}) != bool(review.rule_ids):
                raise ValueError("candidate review status and rule links differ")
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
