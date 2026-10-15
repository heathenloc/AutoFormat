"""Validated version facts and deterministic, escaped Markdown rendering."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


class ReportError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ReportContext:
    task_id: str
    version_id: str
    parent_version_id: str
    source_docx_sha256: str
    output_docx_sha256: str
    brief_version_id: str
    rules_snapshot_id: str
    edit_plan_id: str
    preview_artifact_id: str
    renderer_id: str
    renderer_version: str
    font_fingerprint: str
    template_version_id: str | None = None
    decision_version_id: str | None = None
    created_at: str | None = None


_SCHEMA_PATH = Path(__file__).parent / "schemas" / "version-report-1.0.schema.json"
_VALIDATOR = Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_DONE = {"modified_verified", "already_satisfied"}


def _summary(rules: list[dict], changes: list[dict], cumulative: list[dict],
             issues: list[dict], note: str) -> dict:
    counts = dict(sorted(Counter(rule["status"] for rule in rules).items()))
    pending = sum(count for status, count in counts.items() if status not in _DONE) + len(issues)
    format_status = (
        "unassessed" if not rules else
        "verified" if pending == 0 else "partial"
    )
    return {
        "delivery_status": "ready",
        "format_status": format_status,
        "total_rules": len(rules),
        "status_counts": counts,
        "this_round_change_count": len(changes),
        "cumulative_change_count": len(cumulative),
        "pending_count": pending,
        "note": note,
    }


def build_report(
    context: ReportContext, *, rules: list[dict], changes_this_round: list[dict],
    changes_cumulative: list[dict], decisions: list[dict], issues: list[dict],
    note: str,
) -> dict:
    """Build a fact snapshot; caller supplies only verified editor/parse evidence."""
    created_at = context.created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {
        "schema_version": "version-report/1.0",
        "task_id": context.task_id,
        "version_id": context.version_id,
        "parent_version_id": context.parent_version_id,
        "created_at": created_at,
        "input": {
            "source_docx_sha256": context.source_docx_sha256,
            "brief_version_id": context.brief_version_id,
            "rules_snapshot_id": context.rules_snapshot_id,
            "edit_plan_id": context.edit_plan_id,
            "template_version_id": context.template_version_id,
            "decision_version_id": context.decision_version_id,
        },
        "output_docx_sha256": context.output_docx_sha256,
        "preview": {
            "artifact_id": context.preview_artifact_id,
            "renderer_id": context.renderer_id,
            "renderer_version": context.renderer_version,
            "font_fingerprint": context.font_fingerprint,
        },
        "rules": rules,
        "changes_this_round": changes_this_round,
        "changes_cumulative": changes_cumulative,
        "decisions": decisions,
        "issues": issues,
        "summary": _summary(rules, changes_this_round, changes_cumulative, issues, note),
    }
    validate_report(report)
    return report


def validate_report(report: Any) -> None:
    """Validate schema and relationships that JSON Schema cannot express."""
    try:
        _VALIDATOR.validate(report)
        json.dumps(report, ensure_ascii=False, allow_nan=False)
    except (ValidationError, TypeError, ValueError) as error:
        raise ReportError("Version report does not satisfy version-report/1.0.") from error

    rules = report["rules"]
    rule_map = {rule["rule_id"]: rule for rule in rules}
    if len(rule_map) != len(rules):
        raise ReportError("Version report repeats a rule ID.")
    decisions = report["decisions"]
    decision_ids = {decision["decision_id"] for decision in decisions}
    if len(decision_ids) != len(decisions):
        raise ReportError("Version report repeats a decision ID.")
    for rule in rules:
        if not any(
            ref["source_artifact_id"] == rule["source_artifact_id"] and
            ref["source_version"] == rule["source_version"]
            for ref in rule["evidence_refs"]
        ):
            raise ReportError("A rule has no matching source evidence.")
        if rule["decision_id"] is not None and rule["decision_id"] not in decision_ids:
            raise ReportError("A rule points to a missing decision.")
        if (rule["source_kind"] == "template_observation_confirmed" and
                rule["decision_id"] is None):
            raise ReportError("Template observation lacks user confirmation.")
        if (rule["source_kind"] == "user_feedback" and
                rule["status"] in _DONE and rule["decision_id"] is None):
            raise ReportError("Executed feedback lacks a recorded user decision.")
        if rule["status"] in _DONE:
            if not rule["verification_ref"] or not rule["object_id"]:
                raise ReportError("A completed rule lacks a verification reference or target.")
        elif not rule["next_action"]:
            raise ReportError("An unfinished rule lacks a next action.")

    cumulative = report["changes_cumulative"]
    cumulative_map = {change["change_id"]: change for change in cumulative}
    if len(cumulative_map) != len(cumulative):
        raise ReportError("Version report repeats a cumulative change ID.")
    this_round = report["changes_this_round"]
    if len({change["change_id"] for change in this_round}) != len(this_round):
        raise ReportError("Version report repeats a current change ID.")
    for change in cumulative:
        rule = rule_map.get(change["rule_id"])
        if rule is None or any((
            change["object_id"] != rule["object_id"],
            change["property_id"] != rule["property_id"],
            change["effective_scope"] != rule["effective_scope"],
            change["before_value"] != rule["before_value"],
            change["after_value"] != rule["after_value"],
            change["verification_ref"] != rule["verification_ref"],
        )):
            raise ReportError("A change does not match its rule outcome.")
        expected_status = ("modified_verified" if change["validation_status"] == "verified"
                           else "field_refresh_pending")
        if rule["status"] != expected_status:
            raise ReportError("A change claims a different validation state than its rule.")
    for change in this_round:
        if cumulative_map.get(change["change_id"]) != change:
            raise ReportError("Current change is missing from the cumulative history.")
    for rule in rules:
        if rule["status"] in {"modified_verified", "field_refresh_pending"} and not any(
            change["rule_id"] == rule["rule_id"] for change in cumulative
        ):
            raise ReportError("A changed rule lacks a recorded change.")

    issue_ids = {issue["issue_id"] for issue in report["issues"]}
    if len(issue_ids) != len(report["issues"]):
        raise ReportError("Version report repeats an issue ID.")
    if any(issue["rule_id"] is not None and issue["rule_id"] not in rule_map
           for issue in report["issues"]):
        raise ReportError("A report issue points to a missing rule.")
    expected = _summary(rules, this_round, cumulative, report["issues"],
                        report["summary"]["note"])
    if report["summary"] != expected:
        raise ReportError("Version report summary does not match its facts.")


def _plain(value: Any) -> str:
    if value is None:
        return "未记录"
    raw = (value if isinstance(value, str) else
           json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
    raw = raw.replace("\r", " ").replace("\n", " ")
    escaped = html.escape(raw, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", escaped)


def render_markdown(report: dict) -> str:
    """Render only escaped report facts; no HTML or Markdown from user text."""
    validate_report(report)
    summary = report["summary"]
    lines = [
        "# AutoFormat 版本报告", "",
        f"- 任务：{_plain(report['task_id'])}",
        f"- 当前版本：{_plain(report['version_id'])}",
        f"- 父版本：{_plain(report['parent_version_id'])}",
        f"- 时间：{_plain(report['created_at'])}",
        f"- Brief 版本：{_plain(report['input']['brief_version_id'])}",
        f"- DOCX SHA-256：{_plain(report['output_docx_sha256'])}",
        "", "## 完成情况", "",
        f"- 交付状态：{_plain(summary['delivery_status'])}",
        f"- 格式状态：{_plain(summary['format_status'])}",
        f"- 规则总数：{summary['total_rules']}",
        f"- 本轮变化：{summary['this_round_change_count']}",
        f"- 累计变化：{summary['cumulative_change_count']}",
        f"- 待处理：{summary['pending_count']}",
        f"- 说明：{_plain(summary['note'])}",
    ]
    for status, count in summary["status_counts"].items():
        lines.append(f"- {_plain(status)}：{count}")

    for title, changes in (("本轮变化", report["changes_this_round"]),
                           ("累计变化", report["changes_cumulative"])):
        lines.extend(["", f"## {title}", ""])
        if not changes:
            lines.append("无。")
        for change in changes:
            lines.append(
                f"- {_plain(change['object_id'])} / {_plain(change['property_id'])}："
                f"{_plain(change['before_value'])} → {_plain(change['after_value'])}；"
                f"规则 {_plain(change['rule_id'])}；校验 {_plain(change['validation_status'])}。"
            )

    lines.extend(["", "## 逐条规则", ""])
    if not report["rules"]:
        lines.append("没有已确认的格式规则。")
    for rule in report["rules"]:
        lines.extend([
            f"### {_plain(rule['rule_id'])}", "",
            f"- 原要求：{_plain(rule['original_requirement'])}",
            f"- 来源：{_plain(rule['source_kind'])} / {_plain(rule['source_artifact_id'])} / {_plain(rule['source_version'])}",
            f"- 目标：{_plain(rule['object_id'])} / {_plain(rule['semantic_role'])} / {_plain(rule['property_id'])}",
            f"- 范围：{_plain(rule['requested_scope'])} → {_plain(rule['effective_scope'])}",
            f"- 修改前后：{_plain(rule['before_value'])} → {_plain(rule['after_value'])}",
            f"- 结果：{_plain(rule['status'])}；{_plain(rule['reason'])}",
            f"- 下一步：{_plain(rule['next_action'])}",
            f"- 用户决定：{_plain(rule['decision_id'])}",
            f"- 校验依据：{_plain(rule['verification_ref'])}",
        ])
        for evidence in rule["evidence_refs"]:
            lines.append(
                f"- 原文证据：{_plain(evidence['source_artifact_id'])} / "
                f"{_plain(evidence['source_version'])} / {_plain(evidence['locator'])}："
                f"{_plain(evidence['quote'])}"
            )
        lines.append("")

    lines.extend(["## 用户决定", ""])
    if not report["decisions"]:
        lines.append("无。")
    for decision in report["decisions"]:
        lines.append(
            f"- {_plain(decision['question_id'])}：{_plain(decision['raw_answer'])}；"
            f"归一选择 {_plain(decision['normalized_choice'])}；"
            f"记录 {_plain(decision['decision_id'])}。"
        )

    lines.extend(["", "## 未处理事项", ""])
    pending_rules = [rule for rule in report["rules"] if rule["status"] not in _DONE]
    if not pending_rules and not report["issues"]:
        lines.append("无。")
    for rule in pending_rules:
        lines.append(
            f"- 规则 {_plain(rule['rule_id'])}：{_plain(rule['reason'])}；"
            f"下一步 {_plain(rule['next_action'])}。"
        )
    for issue in report["issues"]:
        lines.append(
            f"- {_plain(issue['status'])} / {_plain(issue['issue_id'])}："
            f"{_plain(issue['reason'])}；下一步 {_plain(issue['next_action'])}。"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_report(json_path: Path, markdown_path: Path, report: dict) -> None:
    validate_report(report)
    if json_path == markdown_path:
        raise ReportError("JSON and Markdown report paths must differ.")
    markdown = render_markdown(report)
    with json_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False)
        stream.write("\n")
    with markdown_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown)
