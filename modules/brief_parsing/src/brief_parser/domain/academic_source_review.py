"""Evidence-linked source decisions and independent formatting coverage review."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel


SourceClass = Literal[
    "explicit_requirement", "example", "background", "template_observation",
    "out_of_scope", "uncertain",
]
ReviewKind = Literal[
    "suspected_omission", "unsupported_format", "recognized_pending",
    "source_uncertain", "unread_source",
]


class AcademicSourceDecision(StrictModel):
    evidence_id: Identifier
    source_class: SourceClass
    reason_code: Identifier
    format_properties: list[Identifier]


class AcademicReviewItem(StrictModel):
    review_id: Identifier
    kind: ReviewKind
    source_id: Identifier
    evidence_ids: list[Identifier]
    property_id: Identifier | None = None
    reason: Annotated[str, Field(min_length=1)]
    next_action: Annotated[str, Field(min_length=1)]


class AcademicSourceReview(StrictModel):
    schema_version: Literal["academic-source-review/1.0", "academic-source-review/1.1", "academic-source-review/1.2"] = "academic-source-review/1.1"
    policy_version: Literal["academic-format-scope/1.0", "academic-format-scope/1.1", "academic-format-scope/1.2"] = "academic-format-scope/1.1"
    source_artifact_id: Identifier
    source_artifact_version: Annotated[int, Field(gt=0)]
    decisions: list[AcademicSourceDecision]
    items: list[AcademicReviewItem]
    classification_counts: dict[SourceClass, Annotated[int, Field(ge=0)]]
    detected_format_property_count: Annotated[int, Field(ge=0)]
    represented_format_property_count: Annotated[int, Field(ge=0)]
    scope_note: str = "仅审计论文格式；字数、词数、篇幅及具体内容要求不提取、不报漏提、不生成问题。"
    coverage_note: str = "词典线索覆盖检查，不是人工标注的召回率，也不代表编辑器已执行。"

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.schema_version.rsplit("/", 1)[-1] != self.policy_version.rsplit("/", 1)[-1]:
            raise ValueError("source review and policy versions differ")
        ids = [item.evidence_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("source review repeats evidence")
        counts: dict[str, int] = {}
        for item in self.decisions:
            counts[item.source_class] = counts.get(item.source_class, 0) + 1
        if {key: value for key, value in self.classification_counts.items() if value} != counts:
            raise ValueError("source classification counts differ from decisions")
        if self.represented_format_property_count > self.detected_format_property_count:
            raise ValueError("represented properties exceed detected properties")
        if len({item.review_id for item in self.items}) != len(self.items):
            raise ValueError("source review repeats an item")
        return self
