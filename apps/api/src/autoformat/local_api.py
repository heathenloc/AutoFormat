"""Loopback-only HTTP boundary for academic intake and confirmed edits.

The browser can classify targets and request execution, but cannot upload rules,
choose a server-side file path, or supply the editor manifest.
"""

from __future__ import annotations

import json
import secrets
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Callable, Literal
from urllib.parse import urlsplit

from brief_parser.errors import BriefParserError, ErrorCode
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
import uvicorn

from .academic_intake import AcademicTaskIntake
from .academic_decisions import AcademicDecisionStore
from brief_parser.application.academic_decisions import AcademicDecisionError, render_decision_snapshot
from brief_parser.domain.academic_decisions import AcademicDecisionRequest
from .initial_draft import InitialDraftPublisher
from .initial_review import InitialDraftRequest, review_state
from .academic_editor import AcademicEditor
from .feedback_contracts import FeedbackSubmission, FeedbackConfirmationRequest, Id as FeedbackId, SelectionTargetConfirmation
from .feedback_store import FeedbackError, FeedbackStore
from .selection_indexes import SelectionIndexes
from .selection_store import SelectionStore
from .feedback_processing import FeedbackProcessor
from .feedback_rules_contracts import FeedbackRulesDecision
from .feedback_rules_store import FeedbackRulesStore
from .feedback_editor import FeedbackEditor
from .feedback_execution import FeedbackExecutor
from .feedback_execution_contracts import FeedbackExecutionRequest
from .workspace_contracts import VersionContinuationRequest
from .version_workspace import VersionWorkspace
from .feedback_work_queue import FeedbackWorkQueues
from .task_catalog import ApplicationInfo, list_tasks
from .feedback_rule_basis import source_loader
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


class LocalWebAssets(StaticFiles):
    """Serve module workers independently of Windows registry MIME mappings."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            suffix = Path(path).suffix.lower()
            fixed_types = {".mjs": "application/javascript", ".js": "application/javascript", ".wasm": "application/wasm"}
            if suffix in fixed_types:
                response.headers["Content-Type"] = fixed_types[suffix]
        return response


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
    "unsupported_target": 422,
    "unsafe_input": 422,
    "stale_base_version": 409,
    "stale_preview": 409,
    "blocked_conflict": 409,
    "validation_failed": 500,
    "render_failed": 500,
}


def _error(status: str, reason: str, *, code: int | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=code or _ERROR_HTTP.get(status, 500),
        content={"status": status, "reason": reason,
                 "next_action": ("Refresh the selected version and review."
                                 if status in {"stale_base_version", "stale_preview"} else
                                 "Review the affected input or contact the task owner.")},
        headers={"Cache-Control": "no-store"},
    )


def create_local_api(
    *, store: VersionStore, snapshots: RuleSnapshotStore,
    indexer: DotnetTargetIndexer | None, editor: DotnetEditor | None,
    renderer_factory: Callable[[Path], PreviewRenderer],
    session_token: str, allowed_origin: str, font_fingerprint: str,
    intake: AcademicTaskIntake | None = None,
    web_dist_dir: Path | None = None,
    selection_indexes: SelectionIndexes | None = None,
    feedback_basis_loader: Callable | None = None,
    application_mode: Literal["configured", "demo"] = "configured",
) -> FastAPI:
    """Create routes for trusted intake and tasks with confirmed rules.

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
    feedback_store = FeedbackStore(store)
    selections = SelectionStore(feedback_store, selection_indexes) if selection_indexes is not None else None
    decision_store = None
    load_basis = feedback_basis_loader or source_loader(store, snapshots, intake)
    def feedback_rules(context):
        basis = load_basis(context)
        return basis.rules if basis else []
    processor = FeedbackProcessor(feedback_store, selection_indexes, selections=selections, rule_loader=feedback_rules)
    feedback_rules_store = FeedbackRulesStore(processor, basis_loader=load_basis)
    feedback_executor = FeedbackExecutor(feedback_rules_store,
        editor=(FeedbackEditor(dotnet_path=editor.dotnet_path, editor_dll=editor.editor_dll,
            expected_editor_sha256=editor.expected_editor_sha256, timeout_seconds=editor.timeout_seconds)
            if isinstance(editor, DotnetEditor) else None),
        renderer_factory=renderer_factory, font_fingerprint=font_fingerprint)
    version_workspace = VersionWorkspace(feedback_store, feedback_rules_store)
    work_queues = FeedbackWorkQueues(feedback_rules_store, feedback_executor)

    @app.get("/api/application")
    def application_info():
        return ApplicationInfo(schema_version="application-info/1.0", mode=application_mode,
                upload_available=intake is not None,
                max_file_bytes=intake.max_file_bytes if intake else None).model_dump(mode="json")

    @app.get("/api/tasks")
    def task_catalog(before: Annotated[int | None, Query(gt=0)] = None):
        return list_tasks(store, before).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/feedback-execution-capability")
    def feedback_execution_capability(task_id: FeedbackId):
        store.list_versions(task_id)
        return {"schema_version": "feedback-execution-capability/1.0",
                "available": feedback_executor.editor is not None and selection_indexes is not None}
    if web_dist_dir is not None:
        web_dist_dir = web_dist_dir.resolve(strict=True)
        if not (web_dist_dir / "index.html").is_file() or not (web_dist_dir / "assets").is_dir():
            raise ValueError("Build the AutoFormat web UI before starting the local host.")
        app.mount("/assets", LocalWebAssets(directory=web_dist_dir / "assets", follow_symlink=False), name="web-assets")

        @app.get("/")
        def web_shell():
            # The fixed shell contains no session token or task data. The host
            # passes its token in a fragment, erased by JS before any API call.
            return FileResponse(web_dist_dir / "index.html", media_type="text/html")

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return _error("needs_user_input", "Only loopback Host is accepted.", code=403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin != allowed_origin:
            return _error("needs_user_input", "Request origin is not this local session.", code=403)
        token = request.headers.get("x-autoformat-session")
        legacy_token = request.headers.get("x-easyformat-session")
        if token is None:
            token = legacy_token or ""
        elif legacy_token is not None and token != legacy_token:
            return _error("needs_user_input", "Conflicting local session tokens.", code=401)
        public_asset = (web_dist_dir is not None and request.method in {"GET", "HEAD"}
                        and (request.url.path == "/" or request.url.path.startswith("/assets/")))
        if not public_asset and not secrets.compare_digest(token.encode("utf-8"),
                                      session_token.encode("utf-8")):
            return _error("needs_user_input", "Local session token is missing or invalid.", code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
            "connect-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' blob:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError):
        return _error("needs_user_input", "Request does not match its versioned contract.")

    async def known_failure(_: Request, error: Exception):
        return _error(error.status, str(error))

    for known_type in (VersionStoreError, RuleSnapshotError, TargetPlanningError,
                       WorkflowError, PreviewError, AcademicDecisionError, FeedbackError):
        app.add_exception_handler(known_type, known_failure)

    @app.exception_handler(BriefParserError)
    async def parse_failure(_: Request, error: BriefParserError):
        input_error = error.code in {
            ErrorCode.INVALID_REQUEST, ErrorCode.SOURCE_UNSUPPORTED,
            ErrorCode.SOURCE_TOO_LARGE, ErrorCode.SOURCE_TOO_MANY_PAGES,
            ErrorCode.SOURCE_EXTRACTED_TOO_LARGE, ErrorCode.SOURCE_MIME_MISMATCH,
            ErrorCode.SOURCE_TEXT_ENCODING, ErrorCode.SOURCE_ARCHIVE_INVALID,
            ErrorCode.SOURCE_ARCHIVE_PATH_TRAVERSAL, ErrorCode.SOURCE_ARCHIVE_BOMB,
            ErrorCode.SOURCE_XML_UNSAFE, ErrorCode.SOURCE_MACRO_ENABLED,
            ErrorCode.SOURCE_ENCRYPTED, ErrorCode.SOURCE_PDF_INVALID,
            ErrorCode.SOURCE_SCANNED_PDF,
        }
        return _error("unsafe_input" if input_error else "validation_failed",
                      error.safe_message, code=422 if input_error else 503)

    if intake is not None:
        decision_store = AcademicDecisionStore(store, intake)
        initial_draft = InitialDraftPublisher(
            store=store, renderer_factory=renderer_factory,
            font_fingerprint=font_fingerprint,
            academic_editor=(AcademicEditor(
                dotnet_path=editor.dotnet_path, editor_dll=editor.editor_dll,
                expected_editor_sha256=editor.expected_editor_sha256,
                timeout_seconds=editor.timeout_seconds,
            ) if isinstance(editor, DotnetEditor) else None),
            decision_store=decision_store,
        )

        async def read_bounded(upload: UploadFile) -> bytes:
            chunks: list[bytes] = []
            total = 0
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > intake.max_file_bytes:
                    raise VersionStoreError("unsafe_input", "Upload exceeds the size limit.")
                chunks.append(chunk)
            return b"".join(chunks)

        @app.post("/api/tasks")
        async def create_task(
            request_id: str = Form(pattern=r"^[a-f0-9]{32}$"),
            model_processing_acknowledged: bool = Form(),
            brief: UploadFile = File(), paper: UploadFile = File(),
        ):
            if not model_processing_acknowledged:
                raise VersionStoreError(
                    "needs_user_input", "Acknowledge Brief model processing before upload.")
            brief_bytes = await read_bounded(brief)
            paper_bytes = await read_bounded(paper)
            result = await intake.create(
                request_id=request_id, brief_filename=brief.filename or "",
                brief=brief_bytes, paper_filename=paper.filename or "",
                paper=paper_bytes,
                model_processing_acknowledged=model_processing_acknowledged,
            )
            review = await run_in_threadpool(review_state, store, decision_store, result.version.task_id)
            first = None
            report = None
            if review["phase"] != "reviewing_requirements":
                first = await run_in_threadpool(
                    initial_draft.publish, result.version, result.bundle)
                report = json.loads(store.artifact_path(
                    first.task_id, first.version_id, "report_json").read_text(encoding="utf-8"))
            return {
                "schema_version": "task-intake/1.2",
                "status": "ready" if first else "needs_user_input",
                "phase": "initial_draft_ready" if first else "reviewing_requirements",
                "task_id": result.version.task_id,
                "base_version_id": result.version.version_id,
                "base_docx_sha256": result.version.docx_sha256,
                "initial_version_id": first.version_id if first else None,
                "initial_docx_sha256": first.docx_sha256 if first else None,
                "initial_format_status": report["summary"]["format_status"] if report else None,
                "pending_count": report["summary"]["pending_count"] if report else review["pending_count"],
                "rules_snapshot_id": review["snapshot_id"],
                "parse_artifact_id": result.bundle.manifest.artifact_id,
                "parse_readiness": result.bundle.requirement_ir.readiness,
                "requirement_count": len(result.bundle.requirement_ir.requirements),
                "replayed": result.replayed,
                "next_action": (
                    "请先为待确认项选择答案或暂时忽略，再生成初稿。" if first is None else
                    "当前初稿未作格式修改，请查看报告。"
                    if report["summary"]["format_status"] == "unassessed" else
                    "下载初稿后可查看待处理项或在预览中微调。"
                ),
            }

        @app.get("/api/tasks/{task_id}/initial-review")
        def initial_review(task_id: str):
            return review_state(store, decision_store, task_id)

        @app.post("/api/tasks/{task_id}/initial-draft")
        def publish_initial_draft(task_id: str, body: InitialDraftRequest):
            original = store.get_version(task_id, body.base_version_id)
            if original.kind != "original" or original.docx_sha256 != body.expected_base_docx_sha256:
                raise VersionStoreError("stale_base_version", "原稿或版本已变化，请刷新后重试。")
            bundle = intake.load_bundle(task_id)
            first = initial_draft.publish(original, bundle, body.expected_snapshot_id)
            state = review_state(store, decision_store, task_id)
            return {**state, "initial_version_id": first.version_id}

        @app.get("/api/tasks/{task_id}/academic-parse")
        def get_academic_parse(task_id: str):
            return intake.load_bundle(task_id).model_dump(mode="json")

        @app.get("/api/tasks/{task_id}/questions")
        def academic_questions(task_id: str, reopen_decision_id: str | None = None):
            return decision_store.questions(task_id, reopen_decision_id)

        @app.post("/api/tasks/{task_id}/decisions")
        def academic_decision(task_id: str, body: AcademicDecisionRequest):
            snapshot, replayed = decision_store.submit(task_id, body)
            return {"status": "ready", "replayed": replayed, "decision_id": snapshot.events[-1].decision_id,
                    "snapshot_id": snapshot.snapshot_id, "revision": snapshot.revision,
                    "next_action": "继续确认或暂时忽略剩余问题；完成后可生成初稿。"}

        @app.get("/api/tasks/{task_id}/resolved-rules")
        def academic_resolved_rules(task_id: str):
            return decision_store.load(task_id).model_dump(mode="json")

        @app.get("/api/tasks/{task_id}/rule-decisions/snapshots")
        def academic_decision_history(task_id: str):
            return {"status": "ready", "snapshots": decision_store.list_snapshots(task_id)}

        @app.get("/api/tasks/{task_id}/rule-decisions/snapshots/{snapshot_id}")
        def academic_decision_snapshot(task_id: str, snapshot_id: str):
            return decision_store.load(task_id, snapshot_id).model_dump(mode="json")

        @app.get("/api/tasks/{task_id}/rule-decisions/report")
        def academic_decision_report(task_id: str, snapshot_id: str | None = None):
            return PlainTextResponse(render_decision_snapshot(decision_store.load(task_id, snapshot_id)), media_type="text/markdown")

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        if intake is not None:
            store.get_academic_intake(task_id)
        try:
            snapshot = snapshots.load(task_id)
        except RuleSnapshotError as error:
            if (error.status != "needs_user_input" or intake is None or
                    store.get_academic_intake(task_id) is None):
                raise
            versions = store.list_versions(task_id)
            initial = next((item for item in versions if item.kind == "output"), None)
            if initial is None:
                return review_state(store, decision_store, task_id)
            report = json.loads(store.artifact_path(
                task_id, initial.version_id, "report_json").read_text(encoding="utf-8"))
            return {
                "status": "ready", "phase": "initial_draft_ready",
                "task_id": task_id,
                "working_version_id": store.working_version_id(task_id),
                "initial_version_id": initial.version_id,
                "rules_snapshot_id": None,
                "initial_format_status": report["summary"]["format_status"],
                "pending_count": report["summary"]["pending_count"],
            }
        return {
            "status": "ready",
            "task_id": task_id,
            "working_version_id": store.working_version_id(task_id),
            "rules_snapshot_id": snapshot.snapshot_id,
        }

    @app.get("/api/tasks/{task_id}/versions")
    def list_versions(task_id: FeedbackId):
        versions = store.list_versions(task_id)
        return {"status": "ready", "working_version_id": store.working_version_id(task_id), "versions": [{
            "version_id": item.version_id,
            "parent_version_id": item.parent_version_id,
            "sequence": item.sequence,
            "kind": item.kind,
            "status": item.status,
            "docx_sha256": item.docx_sha256,
            "created_at": item.created_at,
        } for item in versions]}

    @app.post("/api/tasks/{task_id}/versions/{version_id}/continue")
    def continue_version(task_id: FeedbackId, version_id: FeedbackId, body: VersionContinuationRequest):
        if (body.task_id, body.version_id) != (task_id, version_id):
            raise FeedbackError("stale_base_version", "继续编辑请求与所选版本不一致。")
        return version_workspace.continue_from(body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/work-items")
    def feedback_work_items(task_id: FeedbackId, version_id: FeedbackId,
            before: Annotated[int | None, Query(gt=0)] = None):
        return work_queues.get(task_id, version_id, before=before).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback-context")
    def feedback_context(task_id: FeedbackId, version_id: FeedbackId):
        return feedback_store.context(task_id, version_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback", status_code=202)
    def submit_feedback(task_id: FeedbackId, version_id: FeedbackId, body: FeedbackSubmission):
        # Received means saved for later processing, never edited or verified.
        return feedback_store.submit(task_id, version_id, body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback")
    def list_feedback(task_id: FeedbackId, version_id: FeedbackId):
        return {"status": "ready", "feedback": [receipt.model_dump(mode="json")
                for receipt in feedback_store.list_receipts(task_id, version_id)]}

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}")
    def read_feedback(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId):
        return feedback_store.get(task_id, version_id, feedback_id).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/selection")
    def read_selection(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId):
        if selections is None:
            raise FeedbackError("unsupported_target", "本地定位组件尚未配置；反馈已保存，尚未执行修改。")
        return selections.get(task_id, version_id, feedback_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback/review")
    def review_feedback(task_id: FeedbackId, version_id: FeedbackId, body: FeedbackSubmission):
        return processor.draft(task_id, version_id, body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/analysis")
    def read_feedback_analysis(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId):
        return processor.get(task_id, version_id, feedback_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/analysis/confirm")
    def confirm_feedback_analysis(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId, body: FeedbackConfirmationRequest):
        return processor.confirm(task_id, version_id, feedback_id, body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/rules")
    def read_feedback_rules(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId):
        return feedback_rules_store.review(task_id, version_id, feedback_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/rules/decide")
    def decide_feedback_rules(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId, body: FeedbackRulesDecision):
        return feedback_rules_store.decide(task_id, version_id, feedback_id, body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/feedback-rules/{snapshot_id}")
    def read_feedback_rule_snapshot(task_id: FeedbackId, version_id: FeedbackId, snapshot_id: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]):
        return feedback_rules_store.load(task_id, version_id, snapshot_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback-executions")
    def execute_feedback(task_id: FeedbackId, version_id: FeedbackId, body: FeedbackExecutionRequest):
        if (task_id, version_id) != (body.task_id, body.base_version_id):
            raise FeedbackError("stale_base_version", "执行路径与所选父版本不一致。")
        return feedback_executor.execute(body).model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/feedback-executions/{request_id}")
    def read_feedback_execution(task_id: FeedbackId, request_id: FeedbackId):
        return feedback_executor.get(task_id, request_id).model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/versions/{version_id}/feedback/{feedback_id}/selection/confirm")
    def confirm_selection(task_id: FeedbackId, version_id: FeedbackId, feedback_id: FeedbackId, body: SelectionTargetConfirmation):
        if selections is None:
            raise FeedbackError("unsupported_target", "本地定位组件尚未配置。")
        return selections.confirm(task_id, version_id, feedback_id, body).model_dump(mode="json")

    def require_initial_draft_for_local_edit(task_id: str, version_id: str):
        parent = store.get_version(task_id, version_id)
        if (parent.kind == "original" and store.get_academic_intake(task_id) is not None
                and not any(version.kind == "output" for version in store.list_versions(task_id))):
            raise WorkflowError("needs_user_input", "请先完成编辑前确认并生成初稿，再进行局部修改。")

    @app.get("/api/tasks/{task_id}/versions/{version_id}/body-alignment/review")
    def body_review(task_id: str, version_id: str):
        require_initial_draft_for_local_edit(task_id, version_id)
        if indexer is None:
            raise WorkflowError("unsupported_property", "Editing is unavailable in this preview host.")
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
        require_initial_draft_for_local_edit(task_id, version_id)
        if indexer is None:
            raise WorkflowError("unsupported_property", "Editing is unavailable in this preview host.")
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
        require_initial_draft_for_local_edit(task_id, version_id)
        if indexer is None or editor is None:
            raise WorkflowError("unsupported_property", "Editing is unavailable in this preview host.")
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
                            filename=f"AutoFormat-{version_id}-{kind}.{extension}")

    return app


@dataclass(slots=True)
class BoundLocalApi:
    """A reserved loopback endpoint; the desktop shell owns its token."""

    app: FastAPI
    url: str
    session_token: str = field(repr=False)
    listener: socket.socket
    server: uvicorn.Server | None = field(default=None, init=False, repr=False)

    def ui_url(self, task_id: str | None = None) -> str:
        if task_id is not None and (len(task_id) != 32 or any(char not in "0123456789abcdef" for char in task_id)):
            raise ValueError("Task ID is invalid.")
        return f"{self.url}/#session={self.session_token}" + (f"&task={task_id}" if task_id else "")

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
    indexer: DotnetTargetIndexer | None, editor: DotnetEditor | None,
    renderer_factory: Callable[[Path], PreviewRenderer],
    font_fingerprint: str,
    intake: AcademicTaskIntake | None = None,
    web_dist_dir: Path | None = None,
    selection_indexes: SelectionIndexes | None = None,
    application_mode: Literal["configured", "demo"] = "configured",
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
            allowed_origin=url, font_fingerprint=font_fingerprint, intake=intake,
            web_dist_dir=web_dist_dir,
            selection_indexes=selection_indexes,
            application_mode=application_mode,
        )
        return BoundLocalApi(app, url, token, listener)
    except BaseException:
        listener.close()
        raise
