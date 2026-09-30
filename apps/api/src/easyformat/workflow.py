"""One verified Brief alignment edit from an immutable parent to a ready version.

The caller supplies a confirmed, typed rule. This boundary never interprets Brief
prose or feedback, and only publishes after the editor, preview, and report agree.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, ValidationError

from .preview import PreviewRenderer, _sha256
from .reports import ReportContext, build_report, write_report
from .version_store import (
    VersionRecord, VersionReferences, VersionStore,
    _safe_remove_directory, new_id,
)


_RESULT_SCHEMA = json.loads(
    (Path(__file__).parent / "schemas" / "edit-result-prototype-1.0.schema.json")
    .read_text(encoding="utf-8")
)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)
_HASH = re.compile(r"^[a-f0-9]{64}$")
_PARAGRAPH = re.compile(r"^p:[0-9]{6,}$")
_ALIGNMENTS = {"left", "center", "right", "both"}


class WorkflowError(Exception):
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ConfirmedBriefAlignment:
    rule_id: str
    source_artifact_id: str
    source_version: str
    original_requirement: str
    evidence_locator: str
    evidence_quote: str
    target_object_id: str
    expected_paragraph_text_sha256: str
    value: str
    semantic_role: str

    def validate(self) -> None:
        if (any(not isinstance(value, str) or not value.strip() for value in (
            self.rule_id, self.source_artifact_id, self.source_version,
            self.original_requirement, self.evidence_locator, self.evidence_quote,
            self.semantic_role,
        )) or not _PARAGRAPH.fullmatch(self.target_object_id) or
                not _HASH.fullmatch(self.expected_paragraph_text_sha256) or
                self.value not in _ALIGNMENTS):
            raise WorkflowError("needs_user_input", "Confirmed alignment rule is incomplete.")


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    status: str
    version: VersionRecord | None


class DotnetEditor:
    """Run a pinned, previously built .NET editor without a shell or restore step."""

    def __init__(self, *, dotnet_path: Path, editor_dll: Path,
                 expected_editor_sha256: str, timeout_seconds: int = 60) -> None:
        if (not _HASH.fullmatch(expected_editor_sha256) or timeout_seconds < 1 or
                dotnet_path.is_symlink() or editor_dll.is_symlink()):
            raise WorkflowError("validation_failed", "Editor configuration is invalid.")
        self.dotnet_path = dotnet_path.resolve(strict=True)
        self.editor_dll = editor_dll.resolve(strict=True)
        if not self.dotnet_path.is_file() or not self.editor_dll.is_file():
            raise WorkflowError("validation_failed", "Editor executable is unavailable.")
        self.expected_editor_sha256 = expected_editor_sha256
        self.timeout_seconds = timeout_seconds
        self._check_editor()

    def _check_editor(self) -> None:
        if _sha256(self.editor_dll) != self.expected_editor_sha256:
            raise WorkflowError("validation_failed", "Editor executable hash changed.")

    def apply(self, work_dir: Path, manifest: dict) -> dict:
        self._check_editor()
        manifest_path = work_dir / "manifest.json"
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
        try:
            completed = subprocess.run(
                [str(self.dotnet_path), str(self.editor_dll), "apply",
                 str(work_dir), str(manifest_path)],
                cwd=work_dir, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkflowError("validation_failed", "DOCX editor failed or timed out.") from error
        if len(completed.stdout) > 16_384:
            raise WorkflowError("validation_failed", "DOCX editor result is too large.")
        try:
            result = json.loads(completed.stdout)
            _RESULT_VALIDATOR.validate(result)
        except (ValueError, ValidationError) as error:
            raise WorkflowError("validation_failed", "DOCX editor returned an invalid result.") from error
        if (result["operation_id"] != manifest["operation_id"] or
                (completed.returncode == 0) !=
                (result["status"] in {"ready", "already_satisfied"})):
            raise WorkflowError("validation_failed", "DOCX editor status is inconsistent.")
        return result


def apply_confirmed_alignment(
    *, store: VersionStore, parent: VersionRecord, expected_parent_sha256: str,
    request_id: str, rule: ConfirmedBriefAlignment, references: VersionReferences,
    editor: DotnetEditor,
    renderer_factory: Callable[[Path], PreviewRenderer],
) -> WorkflowResult:
    """Publish one changed DOCX, report, and selectable preview atomically.

    An already satisfied edit returns without making a new version. A stale parent
    or an uncertain editor result never reaches the renderer or version store.
    """
    rule.validate()
    if (not _HASH.fullmatch(expected_parent_sha256) or
            parent.docx_sha256 != expected_parent_sha256 or
            references.brief_version_id != rule.source_version):
        raise WorkflowError("stale_base_version", "Rule or parent references are stale.")
    current = store.get_version(parent.task_id, parent.version_id)
    if current != parent:
        raise WorkflowError("stale_base_version", "Selected parent version changed.")
    parent_docx = store.artifact_path(parent.task_id, parent.version_id, "docx")
    replay = store.find_request_version(parent.task_id, request_id)
    if replay is not None:
        replay_report = json.loads(store.artifact_path(
            replay.task_id, replay.version_id, "report_json").read_text(encoding="utf-8"))
        matching_rule = [item for item in replay_report["rules"]
                         if item["rule_id"] == rule.rule_id]
        expected_evidence = [{
            "source_artifact_id": rule.source_artifact_id,
            "source_version": rule.source_version,
            "locator": rule.evidence_locator, "quote": rule.evidence_quote,
        }]
        if (replay.parent_version_id != parent.version_id or
                replay.references != references or len(matching_rule) != 1 or
                any(matching_rule[0].get(key) != value for key, value in (
                    ("source_kind", "brief_explicit"),
                    ("source_artifact_id", rule.source_artifact_id),
                    ("source_version", rule.source_version),
                    ("original_requirement", rule.original_requirement),
                    ("evidence_refs", expected_evidence),
                    ("object_id", rule.target_object_id),
                    ("semantic_role", rule.semantic_role),
                    ("after_value", rule.value),
                    ("verification_ref", _verification_ref(replay.docx_sha256, rule)),
                ))):
            raise WorkflowError("blocked_conflict", "Request ID was used for different input.")
        return WorkflowResult("ready", replay)
    if store.working_version_id(parent.task_id) != parent.version_id:
        raise WorkflowError("stale_base_version", "Selected working version changed.")
    prior = None
    if parent.kind == "output":
        prior = json.loads(store.artifact_path(
            parent.task_id, parent.version_id, "report_json").read_text(encoding="utf-8"))
        if any(item["rule_id"] == rule.rule_id for item in prior["rules"]):
            raise WorkflowError("blocked_conflict", "Rule ID already exists in this branch.")

    operation_root = store.root / ".operations"
    operation_root.mkdir(exist_ok=True)
    if (operation_root.is_symlink() or
            (hasattr(operation_root, "is_junction") and operation_root.is_junction()) or
            operation_root.resolve().parent != store.root):
        raise WorkflowError("validation_failed", "Operation workspace is redirected.")
    work_dir = operation_root / new_id()
    work_dir.mkdir()
    try:
        source = work_dir / "input.docx"
        candidate = work_dir / "output.docx"
        shutil.copyfile(parent_docx, source)
        if _sha256(source) != expected_parent_sha256:
            raise WorkflowError("stale_base_version", "Parent DOCX changed during copy.")
        operation_id = new_id()
        manifest = {
            "schema_version": "edit-manifest-prototype/1.0",
            "operation_id": operation_id, "rule_id": rule.rule_id,
            "base_version_id": parent.version_id,
            "base_docx_sha256": expected_parent_sha256,
            "input_file": source.name, "output_file": candidate.name,
            "target_object_id": rule.target_object_id,
            "expected_paragraph_text_sha256": rule.expected_paragraph_text_sha256,
            "property": "paragraph.alignment", "value": rule.value,
            "effective_scope": "paragraph",
        }
        result = editor.apply(work_dir, manifest)
        if result["status"] not in {"ready", "already_satisfied"}:
            raise WorkflowError(result["status"], "DOCX editor did not approve this edit.")
        if (not candidate.is_file() or candidate.is_symlink() or
                result["output_docx_sha256"] != _sha256(candidate) or
                result["after_direct_alignment"] != rule.value):
            raise WorkflowError("validation_failed", "DOCX editor output does not match its result.")
        if result["status"] == "already_satisfied":
            if _sha256(candidate) != expected_parent_sha256:
                raise WorkflowError("validation_failed", "No-op editor result changed DOCX bytes.")
            return WorkflowResult("already_satisfied", None)
        if (result["before_direct_alignment"] == rule.value or
                result["output_docx_sha256"] == expected_parent_sha256):
            raise WorkflowError("validation_failed", "Editor reported a change without new bytes.")

        artifact = renderer_factory(work_dir).render(candidate, new_id())
        version_id = new_id()
        verification_ref = _verification_ref(result["output_docx_sha256"], rule)
        rule_fact = {
            "rule_id": rule.rule_id, "source_kind": "brief_explicit",
            "source_artifact_id": rule.source_artifact_id,
            "source_version": rule.source_version,
            "original_requirement": rule.original_requirement,
            "evidence_refs": [{
                "source_artifact_id": rule.source_artifact_id,
                "source_version": rule.source_version,
                "locator": rule.evidence_locator, "quote": rule.evidence_quote,
            }],
            "object_id": rule.target_object_id,
            "semantic_role": rule.semantic_role,
            "property_id": "paragraph.alignment",
            "requested_scope": "paragraph", "effective_scope": "paragraph",
            "before_value": result["before_direct_alignment"],
            "after_value": result["after_direct_alignment"],
            "status": "modified_verified",
            "reason": "Editor verified direct alignment, document text, and other package parts.",
            "next_action": None, "decision_id": None,
            "verification_ref": verification_ref,
        }
        change = {
            "change_id": operation_id, "rule_id": rule.rule_id,
            "object_id": rule.target_object_id,
            "property_id": "paragraph.alignment",
            "before_value": result["before_direct_alignment"],
            "after_value": result["after_direct_alignment"],
            "effective_scope": "paragraph", "validation_status": "verified",
            "verification_ref": verification_ref,
        }
        previous_changes = prior["changes_cumulative"] if prior else []
        context = ReportContext(
            task_id=parent.task_id, version_id=version_id,
            parent_version_id=parent.version_id,
            source_docx_sha256=expected_parent_sha256,
            output_docx_sha256=result["output_docx_sha256"],
            brief_version_id=references.brief_version_id,
            rules_snapshot_id=references.rules_snapshot_id,
            edit_plan_id=references.edit_plan_id,
            preview_artifact_id=artifact.artifact_id,
            renderer_id=artifact.renderer_id,
            renderer_version=artifact.renderer_version,
            font_fingerprint=references.font_fingerprint,
            template_version_id=references.template_version_id,
            decision_version_id=references.decision_version_id,
        )
        report = build_report(
            context, rules=[*(prior["rules"] if prior else []), rule_fact],
            changes_this_round=[change],
            changes_cumulative=[*previous_changes, change],
            decisions=prior["decisions"] if prior else [],
            issues=prior["issues"] if prior else [],
            note="One confirmed Brief paragraph alignment change was verified.",
        )
        report_json, report_markdown = work_dir / "report.json", work_dir / "report.md"
        write_report(report_json, report_markdown, report)
        published = store.publish_version(
            task_id=parent.task_id, version_id=version_id,
            parent_version_id=parent.version_id,
            expected_parent_sha256=expected_parent_sha256,
            request_id=request_id, candidate_docx=candidate,
            report_json=report_json, report_markdown=report_markdown,
            preview_pdf=work_dir / artifact.pdf_relative_path,
            preview_artifact=artifact, references=references,
        )
        return WorkflowResult("ready", published)
    finally:
        _safe_remove_directory(work_dir, operation_root, store.root)


def _verification_ref(output_hash: str, rule: ConfirmedBriefAlignment) -> str:
    return (f"docx:{output_hash}#{rule.target_object_id}/paragraph.alignment"
            f"?source_text_sha256={rule.expected_paragraph_text_sha256}")
