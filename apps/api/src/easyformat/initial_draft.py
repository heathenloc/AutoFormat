"""Publish a first downloadable V1 before any review or preview feedback.

This is the current baseline publisher. It makes no formatting claim until the
automatic rule planner and editors can supply verified operations; unresolved
Brief candidates are recorded in the report instead of being executed as prose.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Callable

from brief_parser.domain.academic_bundle import AcademicParseBundle

from .preview import PreviewRenderer, _sha256
from .reports import ReportContext, build_report, write_report
from .version_store import (
    VersionRecord, VersionReferences, VersionStore, VersionStoreError,
    _safe_remove_directory, new_id,
)


class InitialDraftPublisher:
    """Idempotently publish a transparent V1 copy with report and text preview."""

    def __init__(
        self, *, store: VersionStore,
        renderer_factory: Callable[[Path], PreviewRenderer],
        font_fingerprint: str,
    ) -> None:
        if not font_fingerprint:
            raise ValueError("Font fingerprint is required for initial draft.")
        self.store = store
        self.renderer_factory = renderer_factory
        self.font_fingerprint = font_fingerprint
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
            "next_action": "打开初稿后核对该项目。",
        }

    def publish(self, parent: VersionRecord, bundle: AcademicParseBundle) -> VersionRecord:
        """Create V1 with exact original bytes when no safe editor plan exists yet."""
        with self._lock:
            return self._publish_locked(parent, bundle)

    def _publish_locked(self, parent: VersionRecord, bundle: AcademicParseBundle) -> VersionRecord:
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
            return prior
        if self.store.working_version_id(parent.task_id) != parent.version_id:
            raise VersionStoreError("stale_base_version", "V0 is no longer the working version.")

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
            shutil.copyfile(source, candidate)
            if _sha256(candidate) != parent.docx_sha256:
                raise VersionStoreError("validation_failed", "Initial draft copy differs from V0.")
            artifact = self.renderer_factory(work_dir).render(candidate, new_id())
            version_id = new_id()
            brief_version = (f"{bundle.requirement_ir.artifact_id}:"
                             f"v{bundle.requirement_ir.artifact_version}")
            references = VersionReferences(
                rules_snapshot_id=f"pending:{intake.bundle_sha256}",
                brief_version_id=brief_version,
                edit_plan_id=hashlib.sha256(json.dumps({
                    "kind": "initial-draft/1.0", "base": parent.version_id,
                    "brief": intake.bundle_sha256, "operations": [],
                }, sort_keys=True).encode()).hexdigest(),
                font_fingerprint=self.font_fingerprint,
            )
            issues = [self._issue(
                "requirement", item.id, "needs_user_input",
                f"Brief 候选 {item.id} 尚未通过首次自动执行的安全计划。",
            ) for item in bundle.requirement_ir.requirements]
            issues.extend(self._issue(
                "conflict", item.id, "blocked_conflict",
                f"Brief 冲突 {item.id} 尚未解决。",
            ) for item in bundle.requirement_ir.conflicts)
            issues.extend(self._issue(
                "unresolved", item.id, "needs_user_input",
                f"解析项目 {item.id} 尚未解决。",
            ) for item in bundle.requirement_ir.unresolved_items)
            if bundle.requirement_ir.readiness == "incomplete":
                issues.append(self._issue(
                    "parse", bundle.requirement_ir.artifact_id, "validation_failed",
                    "Brief 解析不完整；本次未修改格式。",
                ))
            context = ReportContext(
                task_id=parent.task_id, version_id=version_id,
                parent_version_id=parent.version_id,
                source_docx_sha256=parent.docx_sha256,
                output_docx_sha256=parent.docx_sha256,
                brief_version_id=brief_version,
                rules_snapshot_id=references.rules_snapshot_id,
                edit_plan_id=references.edit_plan_id,
                preview_artifact_id=artifact.artifact_id,
                renderer_id=artifact.renderer_id,
                renderer_version=artifact.renderer_version,
                font_fingerprint=references.font_fingerprint,
            )
            report = build_report(
                context, rules=[], changes_this_round=[], changes_cumulative=[],
                decisions=[], issues=issues,
                note="当前基线仅复制 V0，未修改任何格式；自动规则计划和更广的编辑能力仍在开发。",
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
            )
        finally:
            _safe_remove_directory(work_dir, operation_root, self.store.root)
