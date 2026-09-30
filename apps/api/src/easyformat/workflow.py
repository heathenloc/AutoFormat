"""One verified Brief alignment edit from an immutable parent to a ready version.

The caller supplies a confirmed, typed rule. This boundary never interprets Brief
prose or feedback, and only publishes after the editor, preview, and report agree.
"""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, ValidationError
from brief_parser.domain.academic_format import AcademicFormatRuleSet

from .preview import PreviewRenderer, _sha256
from .reports import ReportContext, build_report, write_report
from .target_planning import (
    BodyScopeConfirmation, DotnetTargetIndexer, TargetPlanningError,
    build_body_alignment_review, build_confirmed_body_alignment_plan,
)
from .version_store import (
    VersionRecord, VersionReferences, VersionStore,
    _safe_remove_directory, new_id,
)


_RESULT_SCHEMA = json.loads(
    (Path(__file__).parent / "schemas" / "edit-result-prototype-1.0.schema.json")
    .read_text(encoding="utf-8")
)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)
_BATCH_RESULT_VALIDATOR = Draft202012Validator(json.loads(
    (Path(__file__).parent / "schemas" / "edit-batch-result-1.0.schema.json")
    .read_text(encoding="utf-8")
))
_BATCH_MANIFEST_VALIDATOR = Draft202012Validator(json.loads(
    (Path(__file__).parent / "schemas" / "edit-batch-manifest-1.0.schema.json")
    .read_text(encoding="utf-8")
))
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
class ConfirmedBodyAlignment:
    rule_id: str
    source_artifact_id: str
    source_version: str
    original_requirement: str
    evidence_locator: str
    evidence_quote: str
    value: str

    def validate(self) -> None:
        if (any(not isinstance(value, str) or not value.strip() for value in (
            self.rule_id, self.source_artifact_id, self.source_version,
            self.original_requirement, self.evidence_locator, self.evidence_quote,
        )) or self.value not in _ALIGNMENTS):
            raise WorkflowError("needs_user_input", "Confirmed body rule is incomplete.")


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

    def apply_batch(self, work_dir: Path, manifest: dict) -> dict:
        self._check_editor()
        try:
            _BATCH_MANIFEST_VALIDATOR.validate(manifest)
        except ValidationError as error:
            raise WorkflowError("validation_failed", "DOCX batch manifest is invalid.") from error
        manifest_path = work_dir / "batch-manifest.json"
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
        try:
            completed = subprocess.run(
                [str(self.dotnet_path), str(self.editor_dll), "apply-batch",
                 str(work_dir), str(manifest_path)],
                cwd=work_dir, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkflowError("validation_failed", "DOCX batch editor failed or timed out.") from error
        if len(completed.stdout) > 4_194_304:
            raise WorkflowError("validation_failed", "DOCX batch result is too large.")
        try:
            result = json.loads(completed.stdout)
            _BATCH_RESULT_VALIDATOR.validate(result)
        except (ValueError, ValidationError) as error:
            raise WorkflowError("validation_failed", "DOCX batch editor returned invalid data.") from error
        if (result["batch_id"] != manifest["batch_id"] or
                (completed.returncode == 0) !=
                (result["status"] in {"ready", "already_satisfied"})):
            raise WorkflowError("validation_failed", "DOCX batch editor status is inconsistent.")
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


def _body_scope_payload(confirmation: BodyScopeConfirmation, raw_answer: str) -> dict:
    return {
        "scope_kind": "body_paragraphs",
        "base_docx_sha256": confirmation.base_docx_sha256,
        "rules_snapshot_id": confirmation.rules_snapshot_id,
        "review_sha256": confirmation.review_sha256,
        "body_object_ids": list(confirmation.body_object_ids),
        "excluded_object_ids": list(confirmation.excluded_object_ids),
        "raw_answer": raw_answer,
    }


def confirm_body_scope(
    *, store: VersionStore, parent: VersionRecord, request_id: str,
    raw_answer: str, ruleset: AcademicFormatRuleSet, rules_snapshot_id: str,
    indexer: DotnetTargetIndexer, body_object_ids: tuple[str, ...],
    excluded_object_ids: tuple[str, ...],
) -> tuple[BodyScopeConfirmation, dict]:
    """Validate a complete classification before recording the user's answer."""
    if not raw_answer.strip():
        raise WorkflowError("needs_user_input", "Body scope answer is empty.")
    source = store.artifact_path(parent.task_id, parent.version_id, "docx")
    index = indexer.inspect(source, expected_docx_sha256=parent.docx_sha256)
    review = build_body_alignment_review(
        ruleset=ruleset, index=index, base_version_id=parent.version_id,
        expected_base_docx_sha256=parent.docx_sha256,
        rules_snapshot_id=rules_snapshot_id,
    )
    provisional = BodyScopeConfirmation(
        decision_id="pending", base_version_id=parent.version_id,
        base_docx_sha256=parent.docx_sha256,
        rules_snapshot_id=rules_snapshot_id,
        review_sha256=review["review_sha256"],
        body_object_ids=body_object_ids,
        excluded_object_ids=excluded_object_ids,
    )
    build_confirmed_body_alignment_plan(
        ruleset=ruleset, index=index, confirmation=provisional)
    decision = store.record_decision(
        task_id=parent.task_id, base_version_id=parent.version_id,
        request_id=request_id, kind="answer",
        payload=_body_scope_payload(provisional, raw_answer),
    )
    confirmed = replace(provisional, decision_id=decision.decision_id)
    return confirmed, build_confirmed_body_alignment_plan(
        ruleset=ruleset, index=index, confirmation=confirmed)


def apply_confirmed_body_alignment_plan(
    *, store: VersionStore, parent: VersionRecord, request_id: str,
    source_rule: ConfirmedBodyAlignment, ruleset: AcademicFormatRuleSet,
    confirmation: BodyScopeConfirmation,
    plan: dict, references: VersionReferences, indexer: DotnetTargetIndexer,
    editor: DotnetEditor, renderer_factory: Callable[[Path], PreviewRenderer],
) -> WorkflowResult:
    """Apply all confirmed body targets to one immutable child version."""
    source_rule.validate()
    if (parent.version_id != confirmation.base_version_id or
            parent.docx_sha256 != confirmation.base_docx_sha256 or
            references.rules_snapshot_id != confirmation.rules_snapshot_id or
            references.decision_version_id != confirmation.decision_id or
            references.brief_version_id != source_rule.source_version):
        raise WorkflowError("stale_base_version", "Body plan references are stale.")
    selected_parent = store.get_version(parent.task_id, parent.version_id)
    if selected_parent != parent:
        raise WorkflowError("stale_base_version", "Selected parent version changed.")
    parent_docx = store.artifact_path(parent.task_id, parent.version_id, "docx")
    index = indexer.inspect(parent_docx, expected_docx_sha256=parent.docx_sha256)
    expected_plan = build_confirmed_body_alignment_plan(
        ruleset=ruleset, index=index, confirmation=confirmation)
    if (plan != expected_plan or references.edit_plan_id != expected_plan["plan_id"] or
            source_rule.rule_id != plan["rule_id"] or
            source_rule.source_version != plan["source_version"] or
            source_rule.value != plan["value"]):
        raise WorkflowError("validation_failed", "Executable plan differs from confirmed rule or review.")
    matching_rule = [item for item in ruleset.rules if item.rule_id == source_rule.rule_id]
    if (len(matching_rule) != 1 or
            matching_rule[0].source_artifact_id != source_rule.source_artifact_id or
            matching_rule[0].source_version != source_rule.source_version or
            not any(ref.block_id == source_rule.evidence_locator and
                    ref.quote == source_rule.evidence_quote and
                    ref.match_status in {"exact", "normalized"}
                    for ref in matching_rule[0].evidence_refs)):
        raise WorkflowError("validation_failed", "Brief evidence differs from confirmed rule.")
    decisions = [item for item in store.list_decisions(parent.task_id)
                 if item.decision_id == confirmation.decision_id]
    expected_decision = _body_scope_payload(confirmation, decisions[0].payload.get("raw_answer", "")) if decisions else None
    if (len(decisions) != 1 or decisions[0].kind != "answer" or
            decisions[0].base_version_id != parent.version_id or
            decisions[0].payload != expected_decision):
        raise WorkflowError("needs_user_input", "Body scope confirmation is not recorded for this version.")
    decision = decisions[0]

    replay = store.find_request_version(parent.task_id, request_id)
    expected_rule_ids = {f"{source_rule.rule_id}@{item['object_id']}" for item in plan["operations"]}
    if replay is not None:
        replay_report = json.loads(store.artifact_path(
            replay.task_id, replay.version_id, "report_json").read_text(encoding="utf-8"))
        replay_rules = [item for item in replay_report["rules"]
                        if item["rule_id"] in expected_rule_ids]
        expected_evidence = [{
            "source_artifact_id": source_rule.source_artifact_id,
            "source_version": source_rule.source_version,
            "locator": source_rule.evidence_locator,
            "quote": source_rule.evidence_quote,
        }]
        if (replay.parent_version_id != parent.version_id or
                replay.references != references or
                len(replay_rules) != len(expected_rule_ids) or
                any(item["decision_id"] != confirmation.decision_id or
                    item["source_kind"] != "brief_explicit" or
                    item["source_artifact_id"] != source_rule.source_artifact_id or
                    item["source_version"] != source_rule.source_version or
                    item["original_requirement"] != source_rule.original_requirement or
                    item["evidence_refs"] != expected_evidence or
                    item["after_value"] != source_rule.value for item in replay_rules)):
            raise WorkflowError("blocked_conflict", "Request ID was used for different batch input.")
        return WorkflowResult("ready", replay)
    if store.working_version_id(parent.task_id) != parent.version_id:
        raise WorkflowError("stale_base_version", "Selected working version changed.")
    prior = None
    if parent.kind == "output":
        prior = json.loads(store.artifact_path(
            parent.task_id, parent.version_id, "report_json").read_text(encoding="utf-8"))
        if expected_rule_ids & {item["rule_id"] for item in prior["rules"]}:
            raise WorkflowError("blocked_conflict", "Target rule already exists in this branch.")

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
        if _sha256(source) != parent.docx_sha256:
            raise WorkflowError("stale_base_version", "Parent DOCX changed during copy.")
        manifest = {
            "schema_version": "edit-batch-manifest/1.0",
            "batch_id": plan["plan_id"],
            "base_version_id": parent.version_id,
            "base_docx_sha256": parent.docx_sha256,
            "input_file": source.name, "output_file": candidate.name,
            "operations": [{
                "operation_id": item["operation_id"],
                "rule_id": item["rule_id"],
                "target_object_id": item["object_id"],
                "expected_paragraph_text_sha256": item["expected_paragraph_text_sha256"],
                "expected_xml_path": item["xml_path"],
                "property": item["property_id"],
                "value": item["after_value"],
                "effective_scope": item["effective_scope"],
                "expected_before_direct_alignment": item["before_value"],
            } for item in plan["operations"]],
        }
        result = editor.apply_batch(work_dir, manifest)
        if result["status"] not in {"ready", "already_satisfied"}:
            raise WorkflowError(result["status"], "DOCX batch editor rejected the plan.")
        if (not candidate.is_file() or candidate.is_symlink() or
                result["output_docx_sha256"] != _sha256(candidate) or
                len(result["operations"]) != len(plan["operations"])):
            raise WorkflowError("validation_failed", "DOCX batch output does not match its result.")
        for operation, outcome in zip(plan["operations"], result["operations"]):
            if (outcome["operation_id"] != operation["operation_id"] or
                    outcome["target_object_id"] != operation["object_id"] or
                    outcome["before_direct_alignment"] != operation["before_value"] or
                    outcome["after_direct_alignment"] != operation["after_value"] or
                    outcome["status"] != (
                        "already_satisfied" if isinstance(operation["before_value"], str) and
                        operation["before_value"].casefold() == operation["after_value"]
                        else "ready")):
                raise WorkflowError("validation_failed", "Batch verification differs from the plan.")
        if result["status"] == "already_satisfied":
            if result["output_docx_sha256"] != parent.docx_sha256:
                raise WorkflowError("validation_failed", "No-op batch changed DOCX bytes.")
            return WorkflowResult("already_satisfied", None)
        if (result["output_docx_sha256"] == parent.docx_sha256 or
                all(item["status"] == "already_satisfied" for item in result["operations"])):
            raise WorkflowError("validation_failed", "Batch reported change without new bytes.")

        artifact = renderer_factory(work_dir).render(candidate, new_id())
        version_id = new_id()
        output_hash = result["output_docx_sha256"]
        rule_facts, changes = [], []
        for operation, outcome in zip(plan["operations"], result["operations"]):
            verification_ref = (
                f"docx:{output_hash}#{operation['object_id']}/paragraph.alignment"
                f"?source_text_sha256={operation['expected_paragraph_text_sha256']}")
            target_rule_id = f"{source_rule.rule_id}@{operation['object_id']}"
            rule_facts.append({
                "rule_id": target_rule_id, "source_kind": "brief_explicit",
                "source_artifact_id": source_rule.source_artifact_id,
                "source_version": source_rule.source_version,
                "original_requirement": source_rule.original_requirement,
                "evidence_refs": [{
                    "source_artifact_id": source_rule.source_artifact_id,
                    "source_version": source_rule.source_version,
                    "locator": source_rule.evidence_locator,
                    "quote": source_rule.evidence_quote,
                }],
                "object_id": operation["object_id"], "semantic_role": "body",
                "property_id": "paragraph.alignment",
                "requested_scope": "same_kind", "effective_scope": "paragraph",
                "before_value": outcome["before_direct_alignment"],
                "after_value": outcome["after_direct_alignment"],
                "status": ("modified_verified" if outcome["status"] == "ready"
                           else "already_satisfied"),
                "reason": "Batch editor verified direct alignment and preserved unrelated content.",
                "next_action": None, "decision_id": confirmation.decision_id,
                "verification_ref": verification_ref,
            })
            if outcome["status"] == "ready":
                changes.append({
                    "change_id": operation["operation_id"],
                    "rule_id": target_rule_id, "object_id": operation["object_id"],
                    "property_id": "paragraph.alignment",
                    "before_value": outcome["before_direct_alignment"],
                    "after_value": outcome["after_direct_alignment"],
                    "effective_scope": "paragraph", "validation_status": "verified",
                    "verification_ref": verification_ref,
                })
        decision_fact = {
            "decision_id": decision.decision_id,
            "question_id": f"body-scope:{source_rule.rule_id}",
            "raw_answer": decision.payload["raw_answer"],
            "normalized_choice": "confirmed_body_scope",
        }
        previous_decisions = prior["decisions"] if prior else []
        report_decisions = (previous_decisions if any(
            item["decision_id"] == decision.decision_id for item in previous_decisions)
            else [*previous_decisions, decision_fact])
        context = ReportContext(
            task_id=parent.task_id, version_id=version_id,
            parent_version_id=parent.version_id,
            source_docx_sha256=parent.docx_sha256,
            output_docx_sha256=output_hash,
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
        review = build_body_alignment_review(
            ruleset=ruleset, index=index, base_version_id=parent.version_id,
            expected_base_docx_sha256=parent.docx_sha256,
            rules_snapshot_id=references.rules_snapshot_id,
        )
        new_issues = []
        for item in review["source_issues"]:
            new_issues.append({
                "issue_id": "source:" + hashlib.sha256(json.dumps(
                    item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
                "status": "needs_user_input", "rule_id": None, "object_id": None,
                "reason": f"{item['status']}: {item['reason']}",
                "next_action": item["next_action"],
            })
        for item in review["rule_reviews"]:
            if item["rule_id"] == source_rule.rule_id:
                continue
            status = item["status"]
            new_issues.append({
                "issue_id": "rule:" + hashlib.sha256((
                    item["rule_id"] + ":" + status).encode("utf-8")).hexdigest(),
                "status": ("unsupported_property" if status in {"unsupported", "unsupported_property"}
                           else "blocked_conflict" if status == "pending_conflict"
                           else "check_only" if status == "check_only" else "needs_user_input"),
                "rule_id": None, "object_id": None,
                "reason": f"{item['rule_id']} / {item['property_id']}: {status}",
                "next_action": "Review this rule before applying it.",
            })
        previous_issues = prior["issues"] if prior else []
        report_issues = [*previous_issues]
        known_issue_ids = {item["issue_id"] for item in previous_issues}
        for item in new_issues:
            if item["issue_id"] not in known_issue_ids:
                report_issues.append(item)
                known_issue_ids.add(item["issue_id"])
        report = build_report(
            context, rules=[*(prior["rules"] if prior else []), *rule_facts],
            changes_this_round=changes,
            changes_cumulative=[*(prior["changes_cumulative"] if prior else []), *changes],
            decisions=report_decisions, issues=report_issues,
            note=f"Verified {len(changes)} body paragraph alignment changes in one batch.",
        )
        report_json, report_markdown = work_dir / "report.json", work_dir / "report.md"
        write_report(report_json, report_markdown, report)
        published = store.publish_version(
            task_id=parent.task_id, version_id=version_id,
            parent_version_id=parent.version_id,
            expected_parent_sha256=parent.docx_sha256,
            request_id=request_id, candidate_docx=candidate,
            report_json=report_json, report_markdown=report_markdown,
            preview_pdf=work_dir / artifact.pdf_relative_path,
            preview_artifact=artifact, references=references,
        )
        return WorkflowResult("ready", published)
    finally:
        _safe_remove_directory(work_dir, operation_root, store.root)
