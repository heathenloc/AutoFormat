"""Typed applicability and constraints, independent of physical DOCX targets."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel


class ScopeAxis(StrictModel):
    # None means the full domain. Exclusions retain the unlisted remainder.
    include: list[Identifier] | None = None
    exclude: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        if self.include is not None and (not self.include or len(set(self.include)) != len(self.include)):
            raise ValueError("scope inclusion must be nonempty and unique")
        if len(set(self.exclude)) != len(self.exclude):
            raise ValueError("scope exclusions must be unique")
        if self.include is not None and set(self.include) & set(self.exclude):
            raise ValueError("scope inclusion overlaps exclusions")
        return self


class AcademicRuleScope(StrictModel):
    # Roles, characters, regions, chapter, object_ordinal, object_language, medium, channel and
    # property_component. New axes may be reported without granting execution.
    axes: dict[Identifier, ScopeAxis]


class AcademicConstraint(StrictModel):
    operator: Literal["eq", "between", "gte", "lte", "ne"] = "eq"
    lower: float | None = None
    upper: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if any(value is not None and not math.isfinite(value) for value in (self.lower, self.upper)):
            raise ValueError("constraint bounds must be finite")
        required = {"between": (True, True), "gte": (True, False), "lte": (False, True),
                    "eq": (False, False), "ne": (False, False)}[self.operator]
        if (self.lower is not None, self.upper is not None) != required:
            raise ValueError("constraint bounds differ from operator")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("constraint interval is reversed")
        return self


class AcademicCondition(StrictModel):
    original_text: str
    resolution: Literal["known", "unknown"]
    reason: str


class AcademicRuleSemantics(StrictModel):
    schema_version: Literal["academic-rule-semantics/1.0"] = "academic-rule-semantics/1.0"
    scope: AcademicRuleScope
    constraint: AcademicConstraint
    condition: AcademicCondition | None = None


class AcademicRuleRelation(StrictModel):
    relation_id: Identifier
    rule_ids: list[Identifier] = Field(min_length=2, max_length=2)
    kind: Literal["compatible", "disjoint", "conditional_branch", "incompatible", "potential_overlap"]
    intersection: AcademicRuleScope | None = None
    reason: str


class AcademicRuleConflict(StrictModel):
    conflict_id: Identifier
    rule_ids: list[Identifier] = Field(min_length=2, max_length=2)
    intersection: AcademicRuleScope
    certainty: Literal["definite", "potential"]
    reason: str


class AcademicRuleFragment(StrictModel):
    fragment_id: Identifier
    rule_id: Identifier
    scope: AcademicRuleScope
    status: Literal["verified", "pending_conflict", "pending_condition", "check_only"]
    conflict_ids: list[Identifier] = Field(default_factory=list)
    reason: str
