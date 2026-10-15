"""Pre-edit review contracts; decisions do not create a paper version."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from brief_parser.domain.academic_decisions import AcademicQuestion

Id = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class InitialReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["initial-review/1.0"] = "initial-review/1.0"
    task_id: Id
    status: Literal["needs_user_input", "ready"]
    phase: Literal["reviewing_requirements", "ready_to_edit", "initial_draft_ready"]
    base_version_id: Id
    base_docx_sha256: Hash
    working_version_id: Id
    initial_version_id: Id | None
    snapshot_id: Hash
    revision: Annotated[int, Field(ge=0, le=256)]
    pending_count: Annotated[int, Field(ge=0)]
    questions: list[AcademicQuestion]


class InitialDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["initial-draft-request/1.0"] = "initial-draft-request/1.0"
    base_version_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    expected_base_docx_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    expected_snapshot_id: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def outstanding_questions(snapshot):
    return [question for question in snapshot.questions
            if question.status in {"pending", "blocked", "deferred"}]


def review_state(store, decisions, task_id):
    snapshot = decisions.load(task_id)
    versions = store.list_versions(task_id)
    original = next(version for version in versions if version.kind == "original")
    initial = next((version for version in versions if version.kind == "output"), None)
    outstanding = outstanding_questions(snapshot)
    return InitialReview.model_validate({
        "schema_version": "initial-review/1.0", "task_id": task_id,
        "status": "needs_user_input" if outstanding and initial is None else "ready",
        "phase": ("initial_draft_ready" if initial else
                  "reviewing_requirements" if outstanding else "ready_to_edit"),
        "base_version_id": original.version_id,
        "base_docx_sha256": original.docx_sha256,
        "working_version_id": store.working_version_id(task_id),
        "initial_version_id": initial.version_id if initial else None,
        "snapshot_id": snapshot.snapshot_id, "revision": snapshot.revision,
        "pending_count": len(outstanding),
        "questions": [question.model_dump(mode="json") for question in snapshot.questions],
    }).model_dump(mode="json")
