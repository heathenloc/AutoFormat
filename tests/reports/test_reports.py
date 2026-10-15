"""Report provenance, consistency, and safe Markdown checks."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json

import pytest

from autoformat.reports import (
    ReportContext,
    ReportError,
    build_report,
    render_markdown,
    validate_report,
)


def _context() -> ReportContext:
    return ReportContext(
        task_id="task-1", version_id="version-1", parent_version_id="version-0",
        source_docx_sha256="0" * 64, output_docx_sha256="1" * 64,
        brief_version_id="brief-1", rules_snapshot_id="rules-1",
        edit_plan_id="plan-1", preview_artifact_id="preview-1",
        renderer_id="libreoffice", renderer_version="26.8.0.3",
        font_fingerprint="fonts-1", created_at="2026-09-30T00:00:00+00:00",
    )


def _rule() -> dict:
    return {
        "rule_id": "rule-1", "source_kind": "brief_explicit",
        "source_artifact_id": "brief-file-1", "source_version": "brief-1",
        "original_requirement": "正文 <img src=x onerror=alert(1)> [点击](https://example.invalid)",
        "evidence_refs": [{
            "source_artifact_id": "brief-file-1", "source_version": "brief-1",
            "locator": "block:4", "quote": "正文居中",
        }],
        "object_id": "p:000002", "semantic_role": "body",
        "property_id": "paragraph.alignment",
        "requested_scope": "paragraph", "effective_scope": "paragraph",
        "before_value": "left", "after_value": "center",
        "status": "modified_verified", "reason": "Re-read effective alignment.",
        "next_action": None, "decision_id": None,
        "verification_ref": "edit-result-1",
    }


def _change() -> dict:
    return {
        "change_id": "change-1", "rule_id": "rule-1",
        "object_id": "p:000002", "property_id": "paragraph.alignment",
        "before_value": "left", "after_value": "center",
        "effective_scope": "paragraph", "validation_status": "verified",
        "verification_ref": "edit-result-1",
    }


def _report() -> dict:
    return build_report(
        _context(), rules=[_rule()], changes_this_round=[_change()],
        changes_cumulative=[_change()], decisions=[], issues=[],
        note="One confirmed formatting change.",
    )


def test_verified_report_has_traceable_fact_and_escaped_markdown() -> None:
    report = _report()
    assert report["summary"]["format_status"] == "verified"
    assert report["summary"]["status_counts"] == {"modified_verified": 1}
    markdown = render_markdown(report)
    assert "正文居中" in markdown and r"edit\-result\-1" in markdown
    assert "&lt;img src=x onerror=alert(1)&gt;" not in markdown
    assert "&lt;img" in markdown
    assert "\\[点击\\]\\(" in markdown
    assert "<img" not in markdown


def test_template_observation_needs_decision_and_evidence() -> None:
    template = _rule()
    template["source_kind"] = "template_observation_confirmed"
    with pytest.raises(ReportError, match="confirmation"):
        build_report(
            _context(), rules=[template], changes_this_round=[_change()],
            changes_cumulative=[_change()], decisions=[], issues=[], note="test",
        )
    broken = _rule()
    broken["evidence_refs"][0]["source_artifact_id"] = "wrong-source"
    with pytest.raises(ReportError, match="evidence"):
        build_report(
            _context(), rules=[broken], changes_this_round=[_change()],
            changes_cumulative=[_change()], decisions=[], issues=[], note="test",
        )


def test_summary_and_change_claims_cannot_drift_from_facts() -> None:
    report = _report()
    altered = deepcopy(report)
    altered["summary"]["pending_count"] = 3
    with pytest.raises(ReportError, match="summary"):
        validate_report(altered)
    altered = deepcopy(report)
    altered["changes_this_round"][0]["after_value"] = "right"
    with pytest.raises(ReportError, match="cumulative"):
        validate_report(altered)
    altered = deepcopy(report)
    altered["rules"][0]["verification_ref"] = None
    with pytest.raises(ReportError, match="verification"):
        validate_report(altered)


def test_no_rules_is_explicitly_unassessed() -> None:
    report = build_report(
        _context(), rules=[], changes_this_round=[], changes_cumulative=[],
        decisions=[], issues=[{
            "issue_id": "issue-1", "status": "needs_user_input",
            "rule_id": None, "object_id": None,
            "reason": "No confirmed rule yet.", "next_action": "Confirm a rule.",
        }], note="Initial draft copied without a format edit.",
    )
    assert report["summary"]["format_status"] == "unassessed"
    assert report["summary"]["pending_count"] == 1
    assert "未处理事项" in render_markdown(report)


def test_runtime_schema_matches_public_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    public = root / "contracts" / "version-report" / "version-report-1.0.schema.json"
    packaged = root / "apps" / "api" / "src" / "autoformat" / "schemas" / "version-report-1.0.schema.json"
    assert public.read_bytes() == packaged.read_bytes()
    assert json.loads(public.read_text(encoding="utf-8"))["$id"].endswith("/version-report/1.0")
