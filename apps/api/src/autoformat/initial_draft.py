"""Publish V1 after pre-edit questions have been answered or explicitly skipped.

With a configured academic editor, replayed typed rules are applied before V1
publication. Unresolved candidates remain visible; without an editor this keeps
the transparent baseline-copy behavior for parser-only development hosts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Callable

from brief_parser.domain.academic_bundle import AcademicParseBundle

from .academic_editor import AcademicEditor, report_facts
from .academic_decisions import AcademicDecisionStore
from .academic_intake import AcademicTaskIntake
from .initial_review import outstanding_questions

from .preview import PreviewRenderer, _sha256
from .reports import ReportContext, build_report, write_report
from .version_store import (
    VersionRecord, VersionReferences, VersionStore, VersionStoreError,
    _safe_remove_directory, new_id,
)


class InitialDraftPublisher:
    """Idempotently publish an edited V1 with report and selectable text preview."""

    def __init__(
        self, *, store: VersionStore,
        renderer_factory: Callable[[Path], PreviewRenderer],
        font_fingerprint: str,
        academic_editor: AcademicEditor | None = None,
        decision_store: AcademicDecisionStore | None = None,
    ) -> None:
        if not font_fingerprint:
            raise ValueError("Font fingerprint is required for initial draft.")
        self.store = store
        self.renderer_factory = renderer_factory
        self.font_fingerprint = font_fingerprint
        self.academic_editor = academic_editor
        self.decision_store = decision_store or AcademicDecisionStore(
            store, AcademicTaskIntake(store=store, service=None))
        self._lock = threading.Lock()

    @staticmethod
    def _request_id(task_id: str) -> str:
        return hashlib.sha256(f"initial-draft/1.0:{task_id}".encode()).hexdigest()[:32]

    @staticmethod
    def _issue(kind: str, identifier: str, status: str, reason: str) -> dict:
        return {
            "issue_id": f"initial:{kind}:" + hashlib.sha256(identifier.encode()).hexdigest(),
            "status": status, "rule_id": None, "object_id": None,
            "reason": reason,
            "next_action": "可在后续重新确认此项；本次不将未确认候选提升为规则。",
        }

    def publish(self, parent: VersionRecord, bundle: AcademicParseBundle,
                expected_snapshot_id: str | None = None) -> VersionRecord:
        """Apply safe rules automatically; preserve original bytes when none apply."""
        with self._lock:
            return self._publish_locked(parent, bundle, expected_snapshot_id)

    def _publish_locked(self, parent: VersionRecord, bundle: AcademicParseBundle,
                        expected_snapshot_id: str | None = None) -> VersionRecord:
        if parent.kind != "original" or parent.sequence != 0:
            raise VersionStoreError("validation_failed", "Initial draft requires V0.")
        intake = self.store.get_academic_intake(parent.task_id)
        if (intake is None or intake.base_version_id != parent.version_id or
                bundle.manifest.request_id != intake.request_id or
                hashlib.sha256(bundle.model_dump_json().encode()).hexdigest()
                != intake.bundle_sha256):
            raise VersionStoreError("validation_failed", "Initial draft parse binding is invalid.")
        request_id = self._request_id(parent.task_id)
        prior = self.store.find_request_version(parent.task_id, request_id)
        if prior is not None:
            if expected_snapshot_id is not None and prior.references.rules_snapshot_id != expected_snapshot_id:
                raise VersionStoreError("stale_base_version", "初稿已经由其他规则快照生成，请刷新。")
            return prior
        if self.store.working_version_id(parent.task_id) != parent.version_id:
            raise VersionStoreError("stale_base_version", "V0 is no longer the working version.")
        effective_snapshot = self.decision_store.load(parent.task_id)
        if expected_snapshot_id is not None and effective_snapshot.snapshot_id != expected_snapshot_id:
            raise VersionStoreError("stale_base_version", "规则快照已变化，请刷新后生成初稿。")
        if outstanding_questions(effective_snapshot):
            raise VersionStoreError("needs_user_input", "请先选择待确认项的答案或暂时忽略，再开始格式编辑。")

        operation_root = self.store.root / ".operations"
        operation_root.mkdir(exist_ok=True)
        if (operation_root.is_symlink() or
                (hasattr(operation_root, "is_junction") and operation_root.is_junction()) or
                operation_root.resolve().parent != self.store.root):
            raise VersionStoreError("validation_failed", "Initial draft workspace is redirected.")
        work_dir = operation_root / new_id()
        work_dir.mkdir()
        try:
            source = self.store.artifact_path(parent.task_id, parent.version_id, "docx")
            candidate = work_dir / "initial.docx"
            parent_copy = work_dir / "parent.docx"
            shutil.copyfile(source, parent_copy)
            if _sha256(parent_copy) != parent.docx_sha256:
                raise VersionStoreError("validation_failed", "Initial draft copy differs from V0.")
            version_id = new_id()
            edit_result = None
            if self.academic_editor is not None:
                edit_result = self.academic_editor.execute(
                    work_dir, bundle=bundle, snapshot=effective_snapshot,
                    base_version_id=parent.version_id, output_file="initial.docx",
                )
            else:
                shutil.copyfile(parent_copy, candidate)
            artifact = self.renderer_factory(work_dir).render(candidate, new_id())
            brief_version = (f"{bundle.requirement_ir.artifact_id}:"
                             f"v{bundle.requirement_ir.artifact_version}")
            references = VersionReferences(
                rules_snapshot_id=effective_snapshot.snapshot_id if effective_snapshot else f"pending:{intake.bundle_sha256}",
                brief_version_id=brief_version,
                edit_plan_id=hashlib.sha256(json.dumps({
                    "kind": "initial-draft/1.0", "base": parent.version_id,
                    "brief": intake.bundle_sha256, "operations": edit_result["operations"] if edit_result else [],
                }, sort_keys=True).encode()).hexdigest(),
                font_fingerprint=self.font_fingerprint,
            )

            context = ReportContext(
                task_id=parent.task_id, version_id=version_id,
                parent_version_id=parent.version_id,
                source_docx_sha256=parent.docx_sha256,
                output_docx_sha256=_sha256(candidate),
                brief_version_id=brief_version,
                rules_snapshot_id=references.rules_snapshot_id,
                edit_plan_id=references.edit_plan_id,
                preview_artifact_id=artifact.artifact_id,
                renderer_id=artifact.renderer_id,
                renderer_version=artifact.renderer_version,
                font_fingerprint=references.font_fingerprint,
            )
            # The immutable parse Bundle remains unchanged. Report the effective
            # questions instead of re-reporting conflicts that the user resolved.
            issues = [self._issue(
                "review", question.question_id, "needs_user_input",
                "用户暂时忽略此问题：" + question.prompt + "；" + question.reason +
                "；" + "；".join(f"原文：{ref.quote}；位置：{ref.locator.model_dump(exclude_none=True)}"
                                for ref in question.evidence_refs),
            ) for question in effective_snapshot.questions if question.status == "skipped"]
            if bundle.source_review is not None:
                issues.extend(self._issue("unsupported", item.review_id, "unsupported_property", item.reason)
                              for item in bundle.source_review.items if item.kind == "unsupported_format")
            if bundle.requirement_ir.readiness == "incomplete":
                issues.append(self._issue("parse", bundle.requirement_ir.artifact_id, "validation_failed",
                                         "Brief 模型解析有未完成项，仅执行独立证据与完整范围验证通过的规则。"))
            facts, changes, decisions = report_facts(bundle, effective_snapshot, edit_result) if edit_result else ([], [], [
                {"decision_id": event.decision_id, "question_id": event.request.question_id,
                 "raw_answer": event.request.raw_answer or event.request.answer.action,
                 "normalized_choice": event.request.answer.action} for event in effective_snapshot.events])
            report = build_report(
                context, rules=facts, changes_this_round=changes, changes_cumulative=changes,
                decisions=decisions, issues=issues,
                note=(f"首次自动执行 {sum(op['changed'] for op in edit_result['operations'])} 个属性操作；完整范围与逐目标结果保留在规则报告中，字段缓存需独立刷新。"
                      if edit_result else "当前未配置编辑核心，仅复制 V0，未修改任何格式。"),
            )
            report_json = work_dir / "report.json"
            report_markdown = work_dir / "report.md"
            write_report(report_json, report_markdown, report)
            return self.store.publish_version(
                task_id=parent.task_id, version_id=version_id,
                parent_version_id=parent.version_id,
                expected_parent_sha256=parent.docx_sha256,
                request_id=request_id, candidate_docx=candidate,
                report_json=report_json, report_markdown=report_markdown,
                preview_pdf=work_dir / artifact.pdf_relative_path,
                preview_artifact=artifact, references=references,
                expected_academic_snapshot_id=effective_snapshot.snapshot_id,
            )
        finally:
            _safe_remove_directory(work_dir, operation_root, self.store.root)
