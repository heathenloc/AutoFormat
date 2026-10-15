"""Plan, edit, verify, render and atomically publish a selected-parent copy."""
from __future__ import annotations

import json
import shutil
import threading
import time

from .feedback_contracts import canonical_bytes, content_hash
from .feedback_execution_contracts import FeedbackExecution, FeedbackExecutionRequest
from .feedback_execution_guards import check_feedback_inputs
from .feedback_report import feedback_report_facts
from .feedback_store import FeedbackError
from .preview import _sha256
from .reports import ReportContext, build_report, validate_report, write_report
from .version_store import FeedbackVersionReferences, new_id, _safe_remove_directory


class FeedbackExecutor:
    def __init__(self, rules, *, editor, renderer_factory, font_fingerprint):
        self.rules, self.store = rules, rules.versions
        self.editor, self.renderer_factory, self.font_fingerprint = editor, renderer_factory, font_fingerprint
        self._lock = threading.RLock()
        with self.store._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_executions (
                task_id TEXT NOT NULL, request_id TEXT NOT NULL, base_version_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL, request_json TEXT NOT NULL, attempt_id TEXT NOT NULL,
                lease_until REAL NOT NULL, result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                proof_json TEXT, proof_sha256 TEXT, PRIMARY KEY(task_id, request_id))""")

    @staticmethod
    def _decode(row):
        try:
            payload = json.loads(row["result_json"])
            request = FeedbackExecutionRequest.model_validate_json(row["request_json"])
            result = FeedbackExecution.model_validate_json(json.dumps(payload))
            if content_hash(payload) != row["result_sha256"]: raise ValueError()
            if (request.task_id, request.request_id, request.base_version_id, request.expected_snapshot_id) != (result.task_id, result.request_id, result.base_version_id, result.snapshot_id): raise ValueError()
            if row["proof_json"] is not None and content_hash(json.loads(row["proof_json"])) != row["proof_sha256"]: raise ValueError()
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "反馈执行记录无法通过校验。") from error
        if (result.task_id, result.request_id, result.base_version_id, result.snapshot_id) != (row["task_id"], row["request_id"], row["base_version_id"], row["snapshot_id"]):
            raise FeedbackError("validation_failed", "反馈执行记录的身份不一致。")
        return result

    def get(self, task_id, request_id):
        with self.store._transaction() as connection:
            row = connection.execute("SELECT * FROM feedback_executions WHERE task_id=? AND request_id=?", (task_id, request_id)).fetchone()
        if row is None: raise FeedbackError("needs_user_input", "反馈执行记录不存在。")
        result = self._decode(row)
        published = self.store.find_request_version(task_id, request_id)
        if published:
            if published.parent_version_id != result.base_version_id or published.references.feedback_rules_snapshot_id != result.snapshot_id:
                raise FeedbackError("validation_failed", "执行结果与已发布版本不一致。")
            return result.model_copy(update={"phase": "ready", "version_id": published.version_id,
                "error_status": None, "reason": "新版本、报告和预览已发布。"})
        if result.phase == "ready":
            raise FeedbackError("validation_failed", "执行记录缺少对应的已发布版本。")
        return result

    def _update(self, request, attempt, phase, *, version_id=None, error_status=None, reason, proof=None, snapshot=None):
        result = FeedbackExecution(schema_version="feedback-execution/1.0", request_id=request.request_id, task_id=request.task_id,
            base_version_id=request.base_version_id, snapshot_id=request.expected_snapshot_id,
            phase=phase, version_id=version_id, error_status=error_status, reason=reason)
        payload = result.model_dump(mode="json")
        with self.store._transaction() as connection:
            if phase == "no_document_change":
                current = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (request.task_id,)).fetchone()
                head = connection.execute("SELECT snapshot_id FROM feedback_rules_heads WHERE task_id=? AND base_version_id=?", (request.task_id, request.base_version_id)).fetchone()
                if current is None or current[0] != request.base_version_id or head is None or head[0] != request.expected_snapshot_id:
                    raise FeedbackError("blocked_conflict", "核对完成前工作版本或规则快照发生变化。")
                try:
                    check_feedback_inputs(connection, snapshot)
                except (ValueError, TypeError, KeyError) as error:
                    raise FeedbackError("blocked_conflict", "核对完成前反馈来源或决定发生变化。") from error
            changed = connection.execute("UPDATE feedback_executions SET result_json=?,result_sha256=?,lease_until=?,proof_json=COALESCE(?,proof_json),proof_sha256=COALESCE(?,proof_sha256) WHERE task_id=? AND request_id=? AND attempt_id=?",
                (canonical_bytes(payload).decode(), content_hash(payload), time.time()+600,
                 canonical_bytes(proof).decode() if proof else None, content_hash(proof) if proof else None,
                 request.task_id, request.request_id, attempt)).rowcount
            if changed != 1: raise FeedbackError("blocked_conflict", "此执行已被另一次重试替代。")
        return result

    def _fresh(self, request):
        context = self.rules.feedback.context(request.task_id, request.base_version_id)
        if context.context_id != request.expected_context_id or context.base_docx_sha256 != request.expected_base_docx_sha256:
            raise FeedbackError("stale_preview", "所选版本或预览依据已变化。")
        if self.store.working_version_id(request.task_id) != request.base_version_id:
            raise FeedbackError("stale_base_version", "只能从当前工作版本生成新版本。")
        snapshot = self.rules.load(request.task_id, request.base_version_id, request.expected_snapshot_id)
        if snapshot is None or snapshot.status != "ready" or self.rules._head(request.task_id, request.base_version_id) != snapshot.snapshot_id:
            raise FeedbackError("needs_user_input", "规则快照尚未全部确认，或已被其他反馈更新。")
        for analysis in snapshot.inputs:
            if self.rules.processor._fresh(request.task_id, request.base_version_id, analysis.interpretation.feedback_id)[-1] != analysis:
                raise FeedbackError("blocked_conflict", "反馈定位或范围决定发生变化，请重新核对规则。")
        return snapshot

    def execute(self, request):
        request = FeedbackExecutionRequest.model_validate_json(request.model_dump_json())
        with self._lock:
            return self._execute(request)

    def _execute(self, request):
        encoded = canonical_bytes(request.model_dump(mode="json")).decode()
        with self.store._transaction() as connection:
            row = connection.execute("SELECT * FROM feedback_executions WHERE task_id=? AND request_id=?", (request.task_id, request.request_id)).fetchone()
        if row:
            if row["request_json"] != encoded: raise FeedbackError("blocked_conflict", "执行请求 ID 已用于其他内容。")
            prior = self.get(request.task_id, request.request_id)
            if prior.phase in {"ready", "no_document_change"} or prior.phase != "failed" and row["lease_until"] > time.time(): return prior
        if self.editor is None:
            raise FeedbackError("needs_user_input", "当前宿主未配置 DOCX 编辑器和预览渲染器。")
        snapshot = self._fresh(request)
        attempt = new_id()
        initial = FeedbackExecution(schema_version="feedback-execution/1.0", request_id=request.request_id, task_id=request.task_id,
            base_version_id=request.base_version_id, snapshot_id=snapshot.snapshot_id, phase="planning",
            version_id=None, error_status=None, reason="正在生成并核对类型化编辑计划。")
        payload = initial.model_dump(mode="json")
        with self.store._transaction() as connection:
            current = connection.execute("SELECT * FROM feedback_executions WHERE task_id=? AND request_id=?", (request.task_id, request.request_id)).fetchone()
            if current and current["request_json"] != encoded:
                raise FeedbackError("blocked_conflict", "执行请求 ID 已用于其他内容。")
            if current and (not row or current["attempt_id"] != row["attempt_id"]):
                return self._decode(current)
            connection.execute("INSERT INTO feedback_executions VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,request_id) DO UPDATE SET attempt_id=excluded.attempt_id,lease_until=excluded.lease_until,result_json=excluded.result_json,result_sha256=excluded.result_sha256,proof_json=NULL,proof_sha256=NULL",
                (request.task_id, request.request_id, request.base_version_id, snapshot.snapshot_id, encoded,
                 attempt, time.time()+600, canonical_bytes(payload).decode(), content_hash(payload), None, None))
        operation_root = self.store.root / ".operations"
        work = None
        try:
            operation_root.mkdir(exist_ok=True)
            if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (operation_root, *operation_root.parents)) or operation_root.resolve().parent != self.store.root:
                raise FeedbackError("validation_failed", "反馈执行目录发生重定向。")
            work = operation_root / new_id()
            work.mkdir()
            parent = self.store.get_version(request.task_id, request.base_version_id)
            shutil.copyfile(self.store.artifact_path(request.task_id, request.base_version_id, "docx"), work / "parent.docx")
            plan = self.editor.execute(work, snapshot=snapshot, plan_only=True)
            self._update(request, attempt, "editing", reason="正在副本中执行已验证的格式规则。")
            result = self.editor.execute(work, snapshot=snapshot)
            self._update(request, attempt, "validating", reason="正在核对修改结果和来源快照。", proof={"plan": plan, "result": result})
            if self._fresh(request) != snapshot: raise FeedbackError("blocked_conflict", "执行期间规则来源发生变化。")
            if result["status"] == "already_satisfied":
                return self._update(request, attempt, "no_document_change", reason="目标格式已经满足规则，本轮没有 DOCX 变化。", proof={"plan": plan, "result": result}, snapshot=snapshot)
            self._update(request, attempt, "rendering", reason="正在生成新版本的 PDF 预览。")
            candidate = work / "edited.docx"
            artifact = self.renderer_factory(work).render(candidate, new_id())
            previous = json.loads(self.store.artifact_path(request.task_id, request.base_version_id, "report_json").read_text(encoding="utf-8"))
            validate_report(previous)
            facts, changes, decisions = feedback_report_facts(snapshot, result, self.rules.basis_loader(self.rules.feedback.context(request.task_id, request.base_version_id)), self.rules.feedback, previous)
            version_id = new_id()
            references = FeedbackVersionReferences(rules_snapshot_id=parent.references.rules_snapshot_id,
                brief_version_id=parent.references.brief_version_id,
                edit_plan_id=content_hash({"snapshot": snapshot.snapshot_id, "base": parent.version_id, "plan": plan}),
                font_fingerprint=self.font_fingerprint, template_version_id=parent.references.template_version_id,
                decision_version_id=parent.references.decision_version_id, feedback_rules_snapshot_id=snapshot.snapshot_id)
            context = ReportContext(task_id=request.task_id, version_id=version_id, parent_version_id=parent.version_id,
                source_docx_sha256=parent.docx_sha256, output_docx_sha256=_sha256(candidate),
                brief_version_id=references.brief_version_id, rules_snapshot_id=references.rules_snapshot_id,
                edit_plan_id=references.edit_plan_id, preview_artifact_id=artifact.artifact_id,
                renderer_id=artifact.renderer_id, renderer_version=artifact.renderer_version,
                font_fingerprint=references.font_fingerprint, template_version_id=references.template_version_id,
                decision_version_id=references.decision_version_id)
            report = build_report(context, rules=facts, changes_this_round=changes,
                changes_cumulative=[*previous["changes_cumulative"], *changes], decisions=decisions,
                issues=previous["issues"], note="反馈格式规则已执行并逐目标回读；历史变化与用户决定按父版本保留。")
            write_report(work / "report.json", work / "report.md", report)
            if self._fresh(request) != snapshot: raise FeedbackError("blocked_conflict", "预览生成期间规则来源发生变化。")
            self._update(request, attempt, "validating", reason="正在原子发布新版本、报告和预览。")
            published = self.store.publish_version(task_id=request.task_id, version_id=version_id,
                parent_version_id=parent.version_id, expected_parent_sha256=parent.docx_sha256,
                request_id=request.request_id, candidate_docx=candidate, report_json=work / "report.json",
                report_markdown=work / "report.md", preview_pdf=work / artifact.pdf_relative_path,
                preview_artifact=artifact, references=references, expected_feedback_snapshot_id=snapshot.snapshot_id,
                expected_feedback_execution=(request.request_id, attempt))
            return self._update(request, attempt, "ready", version_id=published.version_id, reason="新版本、报告和预览已发布。")
        except Exception as error:
            self._update(request, attempt, "failed", error_status=getattr(error, "status", "validation_failed"),
                reason=str(error)[:4096] if hasattr(error, "status") else "反馈执行失败，当前版本未被替换。")
            raise
        finally:
            if work is not None: _safe_remove_directory(work, operation_root, self.store.root)
