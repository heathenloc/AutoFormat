"""Trusted parser snapshot -> deterministic .NET planner/editor, no prose execution."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from brief_parser.application.academic_decisions import AcademicDecisionEngine
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_decisions import AcademicDecisionSnapshot

from .preview import _sha256
from .workflow import DotnetEditor, WorkflowError

_SCHEMAS = Path(__file__).parent / "schemas"


def _validator(name):
    return Draft202012Validator(json.loads((_SCHEMAS / f"{name}-1.0.schema.json").read_text(encoding="utf-8")))


class AcademicEditor(DotnetEditor):
    """Use the existing pinned executable configuration, with a strict new contract."""

    def execute(self, work_dir: Path, *, bundle: AcademicParseBundle,
                snapshot: AcademicDecisionSnapshot, base_version_id: str,
                input_file: str = "parent.docx", output_file: str = "edited.docx",
                plan_only: bool = False) -> dict:
        bundle = AcademicParseBundle.model_validate_json(bundle.model_dump_json())
        snapshot = AcademicDecisionSnapshot.model_validate_json(snapshot.model_dump_json())
        replay = AcademicDecisionEngine(bundle, task_id=snapshot.task_id,
                                       initial_version_id=snapshot.initial_version_id)
        if replay.compile(snapshot.events) != snapshot:
            raise WorkflowError("validation_failed", "Rule snapshot differs from immutable source replay.")
        for name in (input_file, output_file):
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.docx", name)
                    or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
                raise WorkflowError("validation_failed", "Editor requires task-local simple DOCX filenames.")
        if input_file.casefold() == output_file.casefold():
            raise WorkflowError("validation_failed", "Editor cannot overwrite its parent.")
        work_dir = Path(work_dir)
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (work_dir, *work_dir.parents)):
            raise WorkflowError("validation_failed", "Editor workspace is redirected.")
        work_dir = work_dir.resolve(strict=True)
        source = work_dir / input_file
        if source.is_symlink() or not source.is_file():
            raise WorkflowError("validation_failed", "Parent is absent or redirected.")
        digest = _sha256(source)
        manifest = {
            "schema_version": "academic-edit-manifest/1.0", "base_version_id": base_version_id,
            "base_docx_sha256": digest, "input_file": input_file, "output_file": output_file,
            "rules_snapshot_id": snapshot.snapshot_id,
            "rules": [r.model_dump(mode="json") for r in snapshot.rules],
            "fragments": [f.model_dump(mode="json") for f in snapshot.fragments],
        }
        _validator("academic-edit-manifest").validate(manifest)
        path = work_dir / ("academic-plan-manifest.json" if plan_only else "academic-edit-manifest.json")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        self._check_editor()
        try:
            completed = subprocess.run(
                [str(self.dotnet_path), str(self.editor_dll), "plan-academic" if plan_only else "apply-academic", str(work_dir), str(path)],
                cwd=work_dir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkflowError("validation_failed", "Academic editor failed or timed out.") from error
        if len(completed.stdout.encode("utf-8")) > 32 * 1024 * 1024:
            raise WorkflowError("validation_failed", "Academic editor result exceeds limit.")
        try:
            result = json.loads(completed.stdout)
            _validator("academic-edit-result").validate(result)
            success = result["status"] in {"planned", "ready", "already_satisfied"}
            if ((completed.returncode == 0) != success or result["base_docx_sha256"] != digest
                    or result["rules_snapshot_id"] != snapshot.snapshot_id or _sha256(source) != digest):
                raise ValueError("Result binding differs from selected parent/snapshot.")
            if success:
                rule_ids = {r.rule_id for r in snapshot.rules}
                if len(result["rules"]) != len(rule_ids) or {r["rule_id"] for r in result["rules"]} != rule_ids:
                    raise ValueError("Result dropped or added rules.")
                fragments = {f.fragment_id: f for f in snapshot.fragments}
                for op in result["operations"]:
                    fragment = fragments[op["fragment_id"]]
                    if op["rule_id"] not in rule_ids or fragment.rule_id != op["rule_id"] or fragment.status != "verified":
                        raise ValueError("Operation lacks a verified source fragment.")
                if not plan_only:
                    output = work_dir / output_file
                    if (not result["content_preserved"] or not result["package_validated"] or output.is_symlink()
                            or not output.is_file() or _sha256(output) != result["output_docx_sha256"]):
                        raise ValueError("Edited DOCX differs from validation result.")
            elif (work_dir / output_file).exists() and result["status"] != "output_exists":
                raise ValueError("Failed editor exposed a candidate output.")
        except (ValueError, KeyError, ValidationError) as error:
            raise WorkflowError("validation_failed", "Academic editor returned inconsistent results.") from error
        if not success:
            raise WorkflowError(result["status"], result["reason"])
        with (work_dir / ("academic-plan-result.json" if plan_only else "academic-edit-result.json")).open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return result


def report_facts(bundle, snapshot, result):
    """Map editor facts to the established version-report/1.0 without losing scope."""
    states = {"unsupported": "unsupported_property", "no_target": "needs_user_input", "ambiguous_target": "needs_user_input",
              "pending_manual_check": "field_refresh_pending"}
    source_id = bundle.requirement_ir.artifact_id
    source_version = f"{source_id}:v{bundle.requirement_ir.artifact_version}"
    facts = []
    changes = []
    outcomes = {r["rule_id"]: r for r in result["rules"]}
    fragments = {f.fragment_id: f for f in snapshot.fragments}
    for rule in snapshot.rules:
        outcome = outcomes[rule.rule_id]
        all_ops = [op for op in result["operations"] if op["rule_id"] == rule.rule_id]
        evidence = [{"source_artifact_id": source_id, "source_version": source_version,
                     "locator": json.dumps(ref.locator.model_dump(mode="json"), ensure_ascii=False), "quote": ref.quote}
                    for ref in rule.evidence_refs]
        if not evidence:
            evidence = [{"source_artifact_id": source_id, "source_version": source_version,
                         "locator": "template observations: " + ", ".join(rule.observation_ids), "quote": rule.value.original_text}]
        groups = sorted({op["fragment_id"] for op in all_ops}) if all_ops else [None]
        if all_ops and outcome["status"] in {"pending_conflict", "pending_condition", "ambiguous_target"}:
            groups.append(None)
        for fragment_id in groups:
            ops = [op for op in all_ops if op["fragment_id"] == fragment_id]
            status = ("field_refresh_pending" if any(op["status"] == "pending_manual_check" for op in ops) else
                      "modified_verified" if any(op["status"] == "modified_verified" for op in ops) else
                      "already_satisfied" if ops else states.get(outcome["status"], outcome["status"]))
            if status == "field_refresh_pending" and not any(op["changed"] for op in ops):
                status = "check_only"
            identifier = rule.rule_id if len(groups) == 1 else rule.rule_id + ":" + (fragment_id or "pending")
            fact = {
                "rule_id": identifier, "source_kind": "user_feedback" if rule.source_kind == "user_decision" else rule.source_kind,
                "source_artifact_id": source_id, "source_version": source_version, "original_requirement": rule.value.original_text,
                "evidence_refs": evidence, "object_id": ",".join(dict.fromkeys(op["object_id"] for op in ops)) or None,
                "semantic_role": rule.target.semantic_role, "property_id": rule.property_id,
                "requested_scope": "same_kind", "effective_scope": "same_kind",
                "before_value": {"targets": [{"object_id": op["object_id"], "part": op["part"], "xml_path": op["xml_path"], "characters": op["character_type"], "value": op["before"]} for op in ops]},
                "after_value": {"value": rule.value.normalized, "unit": rule.value.unit, "scope": (fragments[fragment_id].scope if fragment_id else rule.semantics.scope).model_dump(mode="json"), "operations": ops},
                "status": status, "reason": outcome["reason"] + f"；此分片命中 {len(ops)} 个属性操作。", "next_action": None if status in {"already_satisfied", "modified_verified"} else "核对报告中的定位、冲突或字段刷新项目。",
                "decision_id": rule.decision_ids[-1] if rule.decision_ids else None,
                "verification_ref": "academic-edit-result:" + identifier if ops else None,
            }
            facts.append(fact)
            if status in {"modified_verified", "field_refresh_pending"}:
                changes.append({"change_id": "change:" + identifier, "rule_id": identifier,
                                "object_id": fact["object_id"], "property_id": rule.property_id,
                                "before_value": fact["before_value"], "after_value": fact["after_value"],
                                "effective_scope": fact["effective_scope"],
                                "validation_status": "pending_manual_check" if status == "field_refresh_pending" else "verified",
                                "verification_ref": fact["verification_ref"]})
    decisions = [{"decision_id": e.decision_id, "question_id": e.request.question_id,
                  "raw_answer": e.request.raw_answer or json.dumps(e.request.answer.model_dump(mode="json"), ensure_ascii=False),
                  "normalized_choice": e.request.answer.action} for e in snapshot.events]
    return facts, changes, decisions
