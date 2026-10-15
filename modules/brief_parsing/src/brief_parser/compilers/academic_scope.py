"""Deterministic set intersections and residual scopes; no implicit priority."""

from __future__ import annotations

import hashlib
import json
import math

from brief_parser.domain.academic_semantics import (
    AcademicRuleScope, ScopeAxis, AcademicRuleConflict, AcademicRuleFragment, AcademicRuleRelation,
)


CHARACTERS = ["chinese", "latin", "digits", "complex_script", "other"]
SCRIPTS = {"all": CHARACTERS, "chinese": ["chinese"], "cjk": ["chinese"],
           "latin": ["latin"], "latin_extended": ["latin"], "digits": ["digits"],
           "latin_digits": ["latin", "digits"], "complex_script": ["complex_script"]}

# Runtime safeguards, unrelated to the academic document's content limits.
MAX_RULES = 512
MAX_ANALYSIS_ITEMS = 20000
MAX_REMAINDERS = 1024


class SemanticAnalysisLimit(ValueError):
    pass


def stable_id(prefix, *parts):
    return prefix + "_" + hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def axis(include=None, exclude=()):
    if include is not None:
        include = sorted(set(include) - set(exclude))
        if not include:
            return None
        exclude = []
    return ScopeAxis(include=include, exclude=sorted(set(exclude)))


def intersect_axis(a, b):
    if a.include is None:
        included = b.include
    elif b.include is None:
        included = a.include
    else:
        included = set(a.include) & set(b.include)
    return axis(included, set(a.exclude) | set(b.exclude))


def subtract_axis(a, b):
    # A minus B, including the unlisted remainder of an open domain.
    if b.include is not None:
        return axis(a.include, set(a.exclude) | set(b.include))
    included = set(b.exclude)
    if a.include is not None:
        included &= set(a.include)
    return axis(included, a.exclude)


def intersection(a: AcademicRuleScope, b: AcademicRuleScope):
    values = {}
    for key in sorted(set(a.axes) | set(b.axes)):
        value = intersect_axis(a.axes.get(key, ScopeAxis()), b.axes.get(key, ScopeAxis()))
        if value is None:
            return None
        values[key] = value
    return AcademicRuleScope(axes=values)


def subtract_scope(a, b):
    common = intersection(a, b)
    if common is None:
        return [a]
    current = dict(a.axes)
    results = []
    for key in sorted(common.axes):
        original = current.get(key, ScopeAxis())
        remainder = subtract_axis(original, common.axes[key])
        if remainder is not None:
            results.append(AcademicRuleScope(axes={**current, key: remainder}))
        current[key] = common.axes[key]
    return results


def property_family(prop):
    return "page.margin" if prop in {"page.margin.all", "page.margin.top", "page.margin.bottom", "page.margin.left", "page.margin.right"} else prop


def base_scope(role, prop, script="all", filters=None):
    if role in {"latin_text", "latin_digits", "document_text"}:
        roles = None
    elif role == "heading":
        roles = [f"heading_{level}" for level in range(1, 10)]
    elif role == "table" and prop.startswith("font."):
        roles = ["table_header", "table_body", "table_cell"]
    elif role == "toc" and prop.startswith("font."):
        roles = ["toc"] + [f"toc_heading_{level}" for level in range(1, 10)]
    else:
        roles = [role]
    scopes = {"roles": axis(roles), "characters": axis(SCRIPTS.get(script, [script]))}
    if property_family(prop) == "page.margin":
        scopes["property_component"] = axis(["top", "bottom", "left", "right"] if prop.endswith(".all") else [prop.rsplit(".", 1)[-1]])
    for key, value in (filters or {}).items():
        scopes[key] = intersect_axis(scopes.get(key, ScopeAxis()), value)
        if scopes[key] is None:
            raise ValueError("target scope is empty")
    # Script scopes only constrain run formatting, not paragraph geometry.
    if not prop.startswith("font."):
        scopes["characters"] = axis(CHARACTERS)
    return AcademicRuleScope(axes=scopes)


def _interval(rule):
    constraint = rule.semantics.constraint
    value = rule.value.normalized
    if (constraint.operator == "eq" and rule.property_id == "paragraph.line_spacing"
            and isinstance(value, dict) and value.get("mode") in {"exact", "atLeast"}):
        low = float(value["amount"])
        high = low if value["mode"] == "exact" else math.inf
    elif constraint.operator == "eq" and isinstance(value, (int, float)) and not isinstance(value, bool):
        low = high = float(value)
    elif constraint.operator in {"between", "gte", "lte"}:
        low = constraint.lower if constraint.lower is not None else -math.inf
        high = constraint.upper if constraint.upper is not None else math.inf
    else:
        return None
    scale = {"cm": 72 / 2.54, "mm": 72 / 25.4}.get(rule.value.unit, 1)
    return low * scale, high * scale, ("length" if rule.value.unit in {"cm", "mm", "pt"} else rule.value.unit)


def compatible(a, b):
    left, right = _interval(a), _interval(b)
    if left is not None and right is not None:
        return left[2] == right[2] and max(left[0], right[0]) <= min(left[1], right[1]) + 1e-8
    av, bv = a.value.normalized, b.value.normalized
    ac, bc = a.semantics.constraint.operator, b.semantics.constraint.operator
    if ac == bc == "ne":
        return True
    if ac == "ne" or bc == "ne":
        return av != bv
    return av == bv and a.value.unit == b.value.unit


def _base_status(rule):
    if rule.semantics.condition:
        return "pending_condition"
    if getattr(rule, "execution_support", "typed") == "report_only":
        return "check_only"
    return "check_only" if rule.semantics.constraint.operator != "eq" else "verified"


def analyze_rules(rules):
    if len(rules) > MAX_RULES:
        raise SemanticAnalysisLimit("Too many typed rules for bounded scope analysis.")
    relations, conflicts, fragments = [], [], []
    for index, first in enumerate(rules):
        for second in rules[index + 1:]:
            if property_family(first.property_id) != property_family(second.property_id):
                continue
            common = intersection(first.semantics.scope, second.semantics.scope)
            pair = [first.rule_id, second.rule_id]
            unknown = any(rule.semantics.condition and rule.semantics.condition.resolution == "unknown" for rule in (first, second))
            if common is None:
                # Remove submission axes to distinguish branches from object disjointness.
                without_conditions = [AcademicRuleScope(axes={key: value for key, value in rule.semantics.scope.axes.items() if key not in {"medium", "channel"}}) for rule in (first, second)]
                kind = "conditional_branch" if intersection(*without_conditions) is not None else "disjoint"
                reason = "提交条件互斥，保留各分支。" if kind == "conditional_branch" else "实际目标或字符范围没有交集。"
            elif compatible(first, second):
                kind, reason = "compatible", "作用范围相交，格式约束可同时满足。"
            else:
                kind = "potential_overlap" if unknown else "incompatible"
                reason = "条件尚不能判定；相交范围保守待定。" if unknown else "相交范围上的格式约束互斥；不选择默认优先级。"
                conflicts.append(AcademicRuleConflict(conflict_id=stable_id("fmtconf", pair, common.model_dump()), rule_ids=pair,
                                                     intersection=common, certainty="potential" if unknown else "definite", reason=reason))
            relations.append(AcademicRuleRelation(relation_id=stable_id("fmtrel", pair, kind), rule_ids=pair,
                                                  kind=kind, intersection=common, reason=reason))
            if len(relations) + len(conflicts) > MAX_ANALYSIS_ITEMS:
                raise SemanticAnalysisLimit("Scope relation limit exceeded.")
    for rule in rules:
        remaining = [rule.semantics.scope]
        relevant = [item for item in conflicts if rule.rule_id in item.rule_ids]
        for conflict in relevant:
            remaining = [piece for scope in remaining for piece in subtract_scope(scope, conflict.intersection)]
            if len(remaining) > MAX_REMAINDERS:
                raise SemanticAnalysisLimit("Scope remainder limit exceeded.")
        for scope in remaining:
            fragments.append(AcademicRuleFragment(fragment_id=stable_id("fmtpart", rule.rule_id, scope.model_dump(), "clear"),
                             rule_id=rule.rule_id, scope=scope, status=_base_status(rule), reason="此分片没有未决互斥约束；执行仍需编辑能力和对象定位验证。"))
        for conflict in relevant:
            fragments.append(AcademicRuleFragment(fragment_id=stable_id("fmtpart", rule.rule_id, conflict.conflict_id), rule_id=rule.rule_id,
                             scope=conflict.intersection, status="pending_condition" if conflict.certainty == "potential" else "pending_conflict",
                             conflict_ids=[conflict.conflict_id], reason=conflict.reason))
        if len(fragments) + len(conflicts) + len(relations) > MAX_ANALYSIS_ITEMS:
            raise SemanticAnalysisLimit("Scope analysis output limit exceeded.")
    return relations, conflicts, fragments


def render_rule_semantics(ruleset):
    import html
    def safe(value):
        value = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
        for char in ("\\", "`", "*", "_", "[", "]", "|", "#"):
            value = value.replace(char, "\\" + char)
        return value
    lines = ["## 格式规则适用范围与约束", "", "分片保留未受冲突影响的范围；编辑前仍须定位。条件分支和区间不自动选值。", ""]
    for rule in ruleset.rules:
        lines.append(f"- {safe(rule.target.semantic_role)} / {safe(rule.property_id)}：{safe(rule.value.normalized)} {safe(rule.value.unit or '')}；{safe(rule.status)}")
        lines.append("  - 适用范围：" + safe(rule.semantics.scope.model_dump()))
        lines.append("  - 约束：" + safe(rule.semantics.constraint.model_dump(exclude_none=True)))
        if rule.condition:
            lines.append("  - 条件：" + safe(rule.condition))
        if rule.status != "verified":
            for part in ruleset.fragments:
                if part.rule_id == rule.rule_id and part.status == "verified":
                    lines.append("  - 无冲突分片：" + safe(part.scope.model_dump()))
    for item in ruleset.conflicts:
        lines.append("- 冲突范围：" + safe(item.intersection.model_dump()) + "；" + safe(item.reason))
    return "\n".join(lines) + "\n"
