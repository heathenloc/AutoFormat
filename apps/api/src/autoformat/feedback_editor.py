"""Frozen, source-verified fragments -> pinned .NET range editor."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .feedback_execution_contracts import FeedbackEditManifest
from .feedback_rules_contracts import FeedbackRulesSnapshot, FeedbackRulesSnapshotV2
from .preview import _sha256
from .workflow import DotnetEditor, WorkflowError


class FeedbackEditor(DotnetEditor):
    def execute(self, work_dir, *, snapshot, plan_only=False):
        model = FeedbackRulesSnapshotV2 if snapshot.schema_version == "feedback-rule-snapshot/1.2" else FeedbackRulesSnapshot
        snapshot = model.model_validate_json(snapshot.model_dump_json())
        if snapshot.status != "ready":
            raise WorkflowError("needs_user_input", "反馈规则仍有未确认项，不能编辑。")
        root = Path(work_dir)
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (root, *root.parents)):
            raise WorkflowError("validation_failed", "反馈执行目录发生重定向。")
        root = root.resolve(strict=True)
        source, output = root / "parent.docx", root / "edited.docx"
        if not source.is_file() or source.is_symlink() or _sha256(source) != snapshot.base_docx_sha256:
            raise WorkflowError("stale_base_version", "反馈执行的父版本与快照不符。")
        fragments = [f for f in snapshot.fragments if f.status == "verified"]
        ids = {f.rule_id for f in fragments}
        manifest = FeedbackEditManifest.model_validate({
            "schema_version": "feedback-edit-manifest/1.0",
            "base_version_id": snapshot.base_version_id, "base_docx_sha256": snapshot.base_docx_sha256,
            "input_file": "parent.docx", "output_file": "edited.docx", "rules_snapshot_id": snapshot.snapshot_id,
            "rules": [{"rule_id": r.rule_id, "source_kind": r.source_kind, "source_rule_id": r.source_rule_id,
                "property_id": r.property_id, "value": {"original_text": r.original_requirement,
                    "normalized": r.value.normalized, "unit": r.value.unit}} for r in snapshot.rules if r.rule_id in ids],
            "fragments": [{"fragment_id": f.fragment_id, "rule_id": f.rule_id, "property_id": f.property_id,
                **f.span.model_dump()} for f in fragments],
        })
        name = "feedback-plan" if plan_only else "feedback-edit"
        path = root / f"{name}-manifest.json"
        path.write_text(manifest.model_dump_json(), encoding="utf-8")
        self._check_editor()
        try:
            completed = subprocess.run([str(self.dotnet_path), str(self.editor_dll),
                "plan-feedback" if plan_only else "apply-feedback", str(root), str(path)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._check_editor()
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkflowError("validation_failed", "反馈编辑器运行失败或超时。") from error
        try:
            if len(completed.stdout.encode("utf-8")) > 32 * 1024 * 1024: raise ValueError()
            result = json.loads(completed.stdout)
            schema = json.loads((Path(__file__).parent / "schemas/feedback-edit-result-1.0.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(result)
            success = result["status"] in {"ready", "already_satisfied", "planned"}
            if (completed.returncode == 0) != success: raise ValueError()
            if result["base_docx_sha256"] != snapshot.base_docx_sha256 or result["rules_snapshot_id"] != snapshot.snapshot_id or _sha256(source) != snapshot.base_docx_sha256:
                raise ValueError()
            if not success:
                if output.exists(): raise ValueError()
                raise WorkflowError(result["status"], result["reason"])
            if {r["rule_id"] for r in result["rules"]} != ids or len(result["rules"]) != len(ids): raise ValueError()
            by_id = {f.fragment_id: f for f in fragments}
            seen = set()
            for op in result["operations"]:
                fragment = by_id[op["fragment_id"]]
                if (op["rule_id"], op["property_id"], op["object_id"]) != (fragment.rule_id, fragment.property_id, fragment.span.object_id): raise ValueError()
                if op["status"] not in ({"planned", "already_satisfied"} if plan_only else {"modified_verified", "already_satisfied"}): raise ValueError()
                if op["after"] != fragment.value.normalized: raise ValueError()
                seen.add(fragment.fragment_id)
            if seen != set(by_id): raise ValueError()
            if not plan_only and (not result["content_preserved"] or not result["package_validated"] or not output.is_file() or output.is_symlink() or _sha256(output) != result["output_docx_sha256"]): raise ValueError()
        except (ValueError, KeyError, ValidationError) as error:
            raise WorkflowError("validation_failed", "反馈编辑结果未通过完整绑定校验。") from error
        (root / f"{name}-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
