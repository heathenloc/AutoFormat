"""Review template observations by category without authorizing DOCX edits."""

from __future__ import annotations

import hashlib
import html
import json

from brief_parser.adapters.template_layout_v1_0 import TemplateReadResult
from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.domain.template_layout import TemplateLayoutReport, TemplatePropertyGroup


TEMPLATE_STATUS_LABELS = {
    "covered_by_explicit_rule": "明文与模板一致",
    "source_mismatch": "明文与模板版式不同",
    "blocked_by_pending_rule": "明文要求待定",
    "inconsistent_observations": "同类模板对象版式不一致",
    "needs_template_confirmation": "需确认是否沿用模板",
    "unresolved_observation": "模板属性未确定",
}


def _category(role: str) -> str:
    if role in {"page", "page_number", "header", "footer"}:
        return "page"
    if "heading" in role:
        return "heading"
    if role.startswith("table"):
        return "table"
    return role


def _scope_matches(rule_scope: str, observed_scope: str) -> bool:
    return rule_scope == "all" or rule_scope == observed_scope or (
        rule_scope in {"latin", "latin_digits"} and observed_scope in {"latin", "latin_extended"}
    )


def _property_matches(explicit: str | None, observed: str) -> bool:
    return (explicit == observed or explicit == "page.margin.all" and
            observed in {"page.margin.top", "page.margin.bottom", "page.margin.left", "page.margin.right"})


def _same_value(value, unit, expected, expected_unit) -> bool:
    # Word stores most geometry in integer twips. Small cm rounding differences
    # do not imply a contradictory school requirement.
    if unit != expected_unit:
        if {unit, expected_unit} == {"pt", "cm"} and isinstance(value, (int, float)) and isinstance(expected, (int, float)):
            value = value * 2.54 / 72 if unit == "pt" else value
            expected = expected * 2.54 / 72 if expected_unit == "pt" else expected
        else:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return abs(value - expected) <= (0.01 if unit == "cm" or expected_unit == "cm" else 0.001)
    return value == expected


def build_template_groups(observations: list, ruleset: AcademicFormatRuleSet) -> list[TemplatePropertyGroup]:
    by_key = {}
    for item in observations:
        if item.region != "template_candidate" or item.semantic_role in {"unclassified", "table_cell"}:
            continue
        key = (item.semantic_role, item.property_id, item.character_scope, item.unit)
        by_key.setdefault(key, []).append(item)
    groups = []
    for (role, prop, scope, unit), items in sorted(by_key.items(), key=lambda pair: str(pair[0])):
        rules = [rule for rule in ruleset.rules if _property_matches(rule.property_id, prop) and (
            rule.target.semantic_role == role or role == "page" and rule.target.semantic_role == "page"
            or rule.target.semantic_role in {"latin_text", "latin_digits"} and scope.startswith("latin")
        ) and _scope_matches(rule.character_scope, scope)]
        # Global Latin rules can override the all-character font of a role.
        specific = [rule for rule in rules if rule.character_scope != "all"]
        if specific:
            rules = specific
        issues = [issue for issue in ruleset.issues if issue.target and (issue.target.semantic_role == role
                  or issue.target.semantic_role in {"latin_text", "latin_digits"} and scope.startswith("latin"))
                  and (_property_matches(issue.property_id, prop) or prop.startswith((issue.property_id or "") + "."))]
        encoded = {json.dumps(item.value, sort_keys=True, ensure_ascii=False): item.value
                   for item in items if item.resolution == "resolved"}
        values = [encoded[key] for key in sorted(encoded)]
        if issues or any(rule.status != "verified" for rule in rules):
            status, reason = "blocked_by_pending_rule", "已有缺值、条件或冲突待定的明文条目，不能按未提及属性沿用模板。"
        elif any(item.resolution == "unresolved" for item in items):
            status, reason = "unresolved_observation", "存在无法确定的继承、主题或结构值，需要核对后才可确认模板属性。"
        elif rules:
            if all(any(_same_value(value, unit, rule.value.normalized, rule.value.unit) for rule in rules) for value in values):
                status, reason = "covered_by_explicit_rule", "模板观察值与已验证明文要求一致；执行仍以明文规则为依据。"
            else:
                status, reason = "source_mismatch", "模板版式与明文格式值不同；保留两种来源，初稿后核对适用范围及依据。"
        elif len(values) > 1:
            status, reason = "inconsistent_observations", "同类模板对象出现不同观察值，不能自动选择其中一个。"
        else:
            status, reason = "needs_template_confirmation", "明文未规定该属性；可在初稿后按类别决定是否沿用已观察到的模板值。"
        identity = json.dumps([role, prop, scope, unit, [item.observation_id for item in items]], sort_keys=True)
        groups.append(TemplatePropertyGroup(
            group_id="tplgrp_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            category=_category(role), semantic_role=role, property_id=prop, character_scope=scope,
            status=status, observation_ids=[item.observation_id for item in items],
            explicit_rule_ids=[rule.rule_id for rule in rules], values=values, unit=unit,
            reason=reason, next_action=("由已验证明文规则处理。" if status == "covered_by_explicit_rule"
                                      else "初稿后先核对冲突及来源差异，再按类别确认未提及属性；跳过不产生规则。"),
        ))
    priority = {"source_mismatch": 0, "blocked_by_pending_rule": 1, "inconsistent_observations": 2,
                "unresolved_observation": 3, "needs_template_confirmation": 4, "covered_by_explicit_rule": 5}
    return sorted(groups, key=lambda group: (priority[group.status], group.category, group.group_id))


def build_template_report(result: TemplateReadResult, ir: RequirementIR, ruleset: AcademicFormatRuleSet) -> TemplateLayoutReport:
    return TemplateLayoutReport(
        schema_version="academic-template-layout/1.0", reader_version="docx-template-layout/1.0",
        source_artifact_id=ir.artifact_id, source_artifact_version=ir.artifact_version,
        source_profiles=result.profiles, observations=result.observations,
        groups=build_template_groups(result.observations, ruleset), diagnostics=result.diagnostics,
    )


def render_template_report(report: TemplateLayoutReport) -> str:
    def escaped(value):
        text = html.escape(str(value), quote=True).replace("\n", " ").replace("\r", " ")
        for token in ("\\", "`", "*", "_", "[", "]", "|", "#"):
            text = text.replace(token, "\\" + token)
        return text

    lines = ["## Brief 模板版式观察", "", report.scope_note, "",
             f"读取了 {len(report.observations)} 项逻辑版式观察，形成 {len(report.groups)} 组格式属性。", ""]
    index = {item.observation_id: item for item in report.observations}
    for group in report.groups:
        lines += [f"- **{TEMPLATE_STATUS_LABELS[group.status]}**：{escaped(group.semantic_role)} / {escaped(group.property_id)} / {escaped(group.character_scope)}，值 {escaped(group.values)} {escaped(group.unit or '')}",
                  "  - " + escaped(group.reason)]
        for identifier in group.observation_ids[:3]:
            item = index[identifier]
            origins = "; ".join(f"{origin.layer}:{origin.part}:{origin.xpath}" for origin in item.origins)
            lines.append(f"  - 来源 {escaped(item.source_id)}，对象 {escaped(item.location.model_dump(exclude_none=True))}，依据 {escaped(origins)}")
        if len(group.observation_ids) > 3:
            lines.append(f"  - 另有 {len(group.observation_ids) - 3} 个对象，完整位置保留在 JSON。")
    for diagnostic in report.diagnostics:
        lines.append(f"- 读取诊断 {escaped(diagnostic.code)}：{escaped(diagnostic.message)}")
    return "\n".join(lines) + "\n"
