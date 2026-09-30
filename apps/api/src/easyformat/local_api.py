"""Loopback-only HTTP boundary for a trusted, pre-parsed academic task.

The browser can classify targets and request execution, but cannot upload rules,
choose a server-side file path, or supply the editor manifest.
"""

from __future__ import annotations

import secrets
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Callable, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
import uvicorn

from .preview import PreviewError, PreviewRenderer
from .rule_snapshots import RuleSnapshotError, RuleSnapshotStore
from .target_planning import (
    BodyScopeConfirmation, DotnetTargetIndexer, TargetPlanningError,
    build_body_alignment_review, build_confirmed_body_alignment_plan,
)
from .version_store import VersionReferences, VersionStore, VersionStoreError
from .workflow import (
    ConfirmedBodyAlignment, DotnetEditor, WorkflowError,
    apply_confirmed_body_alignment_plan, confirm_body_scope,
)


ObjectId = Annotated[str, Field(pattern=r"^p:[0-9]{6,}$")]


class BodyScopeConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["body-scope-confirmation/1.0"]
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_base_docx_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    body_object_ids: list[ObjectId] = Field(min_length=1, max_length=5000)
    excluded_object_ids: list[ObjectId] = Field(max_length=5000)
    raw_answer: str = Field(min_length=1, max_length=2048)


class BodyPlanExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["body-plan-execution/1.0"]
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_base_docx_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_id: str = Field(pattern=r"^[a-f0-9]{64}$")


_ERROR_HTTP = {
    "needs_user_input": 422,
    "ambiguous_target": 422,
    "unsupported_property": 422,
    "unsafe_input": 422,
    "stale_base_version": 409,
    "blocked_conflict": 409,
    "validation_failed": 500,
    "render_failed": 500,
}


def _error(status: str, reason: str, *, code: int | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=code or _ERROR_HTTP.get(status, 500),
        content={"status": status, "reason": reason,
                 "next_action": ("Refresh the selected version and review."
                                 if status == "stale_base_version" else
                                 "Review the affected input or contact the task owner.")},
        headers={"Cache-Control": "no-store"},
    )


def create_local_api(
    *, store: VersionStore, snapshots: RuleSnapshotStore,
    indexer: DotnetTargetIndexer, editor: DotnetEditor,
    renderer_factory: Callable[[Path], PreviewRenderer],
    session_token: str, allowed_origin: str, font_fingerprint: str,
) -> FastAPI:
    """Create routes for tasks already provisioned by the trusted parse workflow.

    The host must bind this app to 127.0.0.1 on a random port and give the
    session token only to its own UI. No rule registration route is exposed.
    """
    origin = urlsplit(allowed_origin)
    if (len(session_token) < 32 or not session_token.isascii() or
            not font_fingerprint or
            origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"} or
            origin.port is None or origin.path not in {"", "/"} or
            origin.query or origin.fragment or origin.username or origin.password):
        raise ValueError("Local API session configuration is invalid.")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return _error("needs_user_input", "Only loopback Host is accepted.", code=403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin != allowed_origin:
            return _error("needs_user_input", "Request origin is not this local session.", code=403)
        token = request.headers.get("x-easyformat-session", "")
        if not secrets.compare_digest(token.encode("utf-8"),
                                      session_token.encode("utf-8")):
            return _error("needs_user_input", "Local session token is missing or invalid.", code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError):
        return _error("needs_user_input", "Request does not match its versioned contract.")

    async def known_failure(_: Request, error: Exception):
        return _error(error.status, str(error))

    for known_type in (VersionStoreError, RuleSnapshotError, TargetPlanningError,
                       WorkflowError, PreviewError):
        app.add_exception_handler(known_type, known_failure)

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        snapshot = snapshots.load(task_id)
        return {
            "status": "ready",
            "task_id": task_id,
            "working_version_id": store.working_version_id(task_id),
            "rules_snapshot_id": snapshot.snapshot_id,
        }

    @app.get("/api/tasks/{task_id}/versions")
    def list_versions(task_id: str):
        versions = store.list_versions(task_id)
        return {"status": "ready", "versions": [{
            "version_id": item.version_id,
            "parent_version_id": item.parent_version_id,
            "sequence": item.sequence,
            "kind": item.kind,
            "status": item.status,
            "docx_sha256": item.docx_sha256,
            "created_at": item.created_at,
        } for item in versions]}

    @app.get("/api/tasks/{task_id}/versions/{version_id}/body-alignment/review")
    def body_review(task_id: str, version_id: str):
        snapshot = snapshots.load(task_id)
        parent = store.get_version(task_id, version_id)
        source = store.artifact_path(task_id, version_id, "docx")
        index = indexer.inspect(source, expected_docx_sha256=parent.docx_sha256)
        return build_body_alignment_review(
            ruleset=snapshot.ruleset, index=index,
            base_version_id=version_id,
            expected_base_docx_sha256=parent.docx_sha256,
            rules_snapshot_id=snapshot.snapshot_id,
        )

    @app.post("/api/tasks/{task_id}/versions/{version_id}/body-alignment/confirm")
    def confirm_body(task_id: str, version_id: str, body: BodyScopeConfirmRequest):
        snapshot = snapshots.load(task_id)
        parent = store.get_version(task_id, version_id)
        if body.expected_base_docx_sha256 != parent.docx_sha256:
            raise WorkflowError("stale_base_version", "Selected DOCX hash changed.")
        confirmation, plan = confirm_body_scope(
            store=store, parent=parent, request_id=body.request_id,
            raw_answer=body.raw_answer, ruleset=snapshot.ruleset,
            rules_snapshot_id=snapshot.snapshot_id, indexer=indexer,
            body_object_ids=tuple(body.body_object_ids),
            excluded_object_ids=tuple(body.excluded_object_ids),
            expected_review_sha256=body.review_sha256,
        )
        return {"status": "ready", "decision_id": confirmation.decision_id,
                "plan": plan}

    @app.post("/api/tasks/{task_id}/versions/{version_id}/body-alignment/execute")
    def execute_body(task_id: str, version_id: str, body: BodyPlanExecuteRequest):
        snapshot = snapshots.load(task_id)
        parent = store.get_version(task_id, version_id)
        if body.expected_base_docx_sha256 != parent.docx_sha256:
            raise WorkflowError("stale_base_version", "Selected DOCX hash changed.")
        decisions = [item for item in store.list_decisions(task_id)
                     if item.decision_id == body.decision_id and
                     item.base_version_id == version_id and item.kind == "answer"]
        if len(decisions) != 1:
            raise WorkflowError("needs_user_input", "Body scope decision is unavailable.")
        payload = decisions[0].payload
        try:
            if payload["scope_kind"] != "body_paragraphs":
                raise ValueError("Wrong decision kind.")
            confirmation = BodyScopeConfirmation(
                decision_id=body.decision_id, base_version_id=version_id,
                base_docx_sha256=payload["base_docx_sha256"],
                rules_snapshot_id=payload["rules_snapshot_id"],
                review_sha256=payload["review_sha256"],
                body_object_ids=tuple(payload["body_object_ids"]),
                excluded_object_ids=tuple(payload["excluded_object_ids"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WorkflowError("validation_failed", "Recorded scope decision is invalid.") from error
        source = store.artifact_path(task_id, version_id, "docx")
        index = indexer.inspect(source, expected_docx_sha256=parent.docx_sha256)
        plan = build_confirmed_body_alignment_plan(
            ruleset=snapshot.ruleset, index=index, confirmation=confirmation)
        if plan["plan_id"] != body.plan_id:
            raise WorkflowError("stale_base_version", "Submitted edit plan changed.")
        matching = [item for item in snapshot.ruleset.rules
                    if item.rule_id == plan["rule_id"]]
        if len(matching) != 1:
            raise WorkflowError("validation_failed", "Plan rule is unavailable.")
        rule = matching[0]
        evidence = next((ref for ref in rule.evidence_refs
                         if ref.match_status in {"exact", "normalized"}), None)
        if evidence is None:
            raise WorkflowError("needs_user_input", "Plan rule has no verified Brief evidence.")
        source_rule = ConfirmedBodyAlignment(
            rule_id=rule.rule_id, source_artifact_id=rule.source_artifact_id,
            source_version=rule.source_version,
            original_requirement=evidence.quote,
            evidence_locator=evidence.block_id, evidence_quote=evidence.quote,
            value=plan["value"],
        )
        references = VersionReferences(
            rules_snapshot_id=snapshot.snapshot_id,
            brief_version_id=rule.source_version,
            edit_plan_id=plan["plan_id"],
            decision_version_id=body.decision_id,
            font_fingerprint=font_fingerprint,
        )
        result = apply_confirmed_body_alignment_plan(
            store=store, parent=parent, request_id=body.request_id,
            source_rule=source_rule, ruleset=snapshot.ruleset,
            confirmation=confirmation, plan=plan,
            references=references, indexer=indexer, editor=editor,
            renderer_factory=renderer_factory,
        )
        return {"status": result.status,
                "version_id": result.version.version_id if result.version else None,
                "docx_sha256": result.version.docx_sha256 if result.version else None,
                "preview_artifact_id": (result.version.preview_artifact_id
                                        if result.version else None)}

    @app.get("/api/tasks/{task_id}/versions/{version_id}/artifacts/{kind}")
    def get_artifact(task_id: str, version_id: str, kind: str):
        names = {
            "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
            "report_json": ("application/json", "json"),
            "report_markdown": ("text/markdown", "md"),
            "preview": ("application/pdf", "pdf"),
        }
        if kind not in names:
            raise WorkflowError("unsupported_property", "Artifact kind is not registered.")
        path = store.artifact_path(task_id, version_id, kind)
        media_type, extension = names[kind]
        return FileResponse(path, media_type=media_type,
                            filename=f"EasyFormat-{version_id}-{kind}.{extension}")

    return app


@dataclass(slots=True)
class BoundLocalApi:
    """A reserved loopback endpoint; the desktop shell owns its token."""

    app: FastAPI
    url: str
    session_token: str = field(repr=False)
    listener: socket.socket
    server: uvicorn.Server | None = field(default=None, init=False, repr=False)

    def serve(self) -> None:
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=self.listener.getsockname()[1],
            access_log=False, proxy_headers=False, log_level="warning",
        )
        try:
            self.server = uvicorn.Server(config)
            self.server.run(sockets=[self.listener])
        finally:
            self.listener.close()

    def close(self) -> None:
        if self.server is None:
            self.listener.close()
        else:
            self.server.should_exit = True


def bind_local_api(
    *, store: VersionStore, snapshots: RuleSnapshotStore,
    indexer: DotnetTargetIndexer, editor: DotnetEditor,
    renderer_factory: Callable[[Path], PreviewRenderer],
    font_fingerprint: str,
) -> BoundLocalApi:
    """Reserve a random 127.0.0.1 port before building the origin-bound app."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.set_inheritable(False)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        token = secrets.token_urlsafe(48)
        app = create_local_api(
            store=store, snapshots=snapshots, indexer=indexer, editor=editor,
            renderer_factory=renderer_factory, session_token=token,
            allowed_origin=url, font_fingerprint=font_fingerprint,
        )
        return BoundLocalApi(app, url, token, listener)
    except BaseException:
        listener.close()
        raise
