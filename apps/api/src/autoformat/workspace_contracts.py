"""Version-bound work queues and explicit, idempotent continuation requests."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .feedback_contracts import Contract, Hash, Id, Text, Scope, _check_digest


class VersionContinuationRequest(Contract):
    schema_version: Literal["version-continuation-request/1.0"]
    request_id: Id
    task_id: Id
    version_id: Id
    expected_docx_sha256: Hash
    expected_working_version_id: Id


class VersionContinuation(Contract):
    schema_version: Literal["version-continuation/1.0"]
    request_id: Id
    task_id: Id
    continued_version_id: Id
    previous_working_version_id: Id
    working_version_id: Id
    replayed: bool


class FeedbackWorkItem(Contract):
    feedback_id: Id
    created_at: Text
    raw_text: Text
    requested_scope: Scope
    selected_text: Text | None
    status: Literal["needs_target", "needs_value", "needs_scope", "needs_conflict", "ready",
        "executing", "failed", "completed", "no_document_change", "rule_kept", "question", "out_of_scope", "blocked", "invalid"]
    reason: Text
    execution_request_id: Id | None
    output_version_id: Id | None

    @model_validator(mode="after")
    def check_output(self):
        if (self.status == "completed") != (self.output_version_id is not None):
            raise ValueError("Only a published item has an output version.")
        if self.status in {"executing", "failed", "completed", "no_document_change"} and self.execution_request_id is None:
            raise ValueError("Execution state requires an execution request.")
        return self


class FeedbackWorkQueue(Contract):
    schema_version: Literal["feedback-work-queue/1.0"]
    queue_id: Hash
    task_id: Id
    base_version_id: Id
    base_docx_sha256: Hash
    version_context_id: Hash
    working_version_id: Id
    rules_snapshot_id: Hash | None
    items: Annotated[list[FeedbackWorkItem], Field(max_length=50)]
    next_before: Annotated[int, Field(gt=0)] | None

    @model_validator(mode="after")
    def check_queue(self):
        if len({item.feedback_id for item in self.items}) != len(self.items):
            raise ValueError("Repeated feedback identity.")
        _check_digest(self, "queue_id")
        return self


WORKSPACE_CONTRACTS = {
    "version-continuation-request/1.0": VersionContinuationRequest,
    "version-continuation/1.0": VersionContinuation,
    "feedback-work-queue/1.0": FeedbackWorkQueue,
}
