"""Typed execution requests and explicit DOCX targets; raw text is never a command."""
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .feedback_contracts import Contract, Hash, Id, Key, Label, Text
from brief_parser.validators.academic_decisions import typed_property, validate_format_value


class FeedbackExecutionRequest(Contract):
    schema_version: Literal["feedback-execution-request/1.0"]
    request_id: Id
    task_id: Id
    base_version_id: Id
    expected_base_docx_sha256: Hash
    expected_context_id: Hash
    expected_snapshot_id: Hash


class FeedbackExecution(Contract):
    schema_version: Literal["feedback-execution/1.0"]
    request_id: Id
    task_id: Id
    base_version_id: Id
    snapshot_id: Hash
    phase: Literal["planning", "editing", "validating", "rendering", "ready", "no_document_change", "failed"]
    version_id: Id | None
    error_status: Label | None
    reason: Text

    @model_validator(mode="after")
    def check_phase(self):
        if (self.phase == "ready") != (self.version_id is not None):
            raise ValueError("Only a published execution has an output version.")
        if (self.phase == "failed") != (self.error_status is not None):
            raise ValueError("Only a failed execution has an error status.")
        return self


class FeedbackEditValue(Contract):
    original_text: Text
    normalized: JsonValue
    unit: Label | None
    dictionary_version: Label = "academic-properties/1.0"


class FeedbackEditRule(Contract):
    rule_id: Key
    source_kind: Literal["academic", "feedback"]
    source_rule_id: Key
    property_id: Label
    value: FeedbackEditValue

    @model_validator(mode="after")
    def check_value(self):
        if not typed_property(self.property_id): raise ValueError("Unregistered format property.")
        validate_format_value(self.property_id, self.value.normalized, self.value.unit)
        return self


class FeedbackEditFragment(Contract):
    fragment_id: Hash
    rule_id: Key
    property_id: Label
    object_id: Key
    start_utf16: Annotated[int, Field(ge=0)] | None
    length_utf16: Annotated[int, Field(gt=0)] | None

    @model_validator(mode="after")
    def check_range(self):
        if (self.start_utf16 is None) != (self.length_utf16 is None): raise ValueError("Incomplete range.")
        if self.property_id.startswith("font.") != (self.start_utf16 is not None): raise ValueError("Range does not match the property minimum unit.")
        if not self.object_id.startswith("o:"): raise ValueError("Target is not an academic DOCX object.")
        return self


class FeedbackEditManifest(Contract):
    schema_version: Literal["feedback-edit-manifest/1.0"]
    base_version_id: Id
    base_docx_sha256: Hash
    input_file: Label
    output_file: Label
    rules_snapshot_id: Hash
    rules: Annotated[list[FeedbackEditRule], Field(max_length=1024)]
    fragments: Annotated[list[FeedbackEditFragment], Field(max_length=20000)]

    @model_validator(mode="after")
    def check_manifest(self):
        rules = {r.rule_id: r for r in self.rules}
        if len(rules) != len(self.rules) or len({f.fragment_id for f in self.fragments}) != len(self.fragments):
            raise ValueError("Repeated rule/fragment ID.")
        if self.input_file != "parent.docx" or self.output_file != "edited.docx":
            raise ValueError("Unexpected task-local file name.")
        for fragment in self.fragments:
            rule = rules.get(fragment.rule_id)
            if rule is None or fragment.property_id != rule.property_id and not (rule.property_id == "page.margin.all" and fragment.property_id in {"page.margin.top", "page.margin.bottom", "page.margin.left", "page.margin.right"}):
                raise ValueError("Fragment property differs from its source rule.")
        if set(rules) != {f.rule_id for f in self.fragments}: raise ValueError("A rule has no executable fragment.")
        return self


EXECUTION_CONTRACTS = {"feedback-execution-request/1.0": FeedbackExecutionRequest,
    "feedback-execution/1.0": FeedbackExecution, "feedback-edit-manifest/1.0": FeedbackEditManifest}
