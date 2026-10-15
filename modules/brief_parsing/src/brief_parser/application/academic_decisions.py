"""Deterministic question -> answer -> rule snapshot loop for academic parsing."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from brief_parser.compilers.academic_scope import analyze_rules, axis, base_scope, compatible, intersection, stable_id, subtract_scope, SemanticAnalysisLimit
from brief_parser.compilers.academic_common_v1_3 import AcademicCommonFormatExtractor as LiteralExtractor, _TARGET
from brief_parser.compilers.academic_semantic_extractor import parse_condition
from brief_parser.compilers.template_layout import build_template_groups
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_format import AcademicTarget, AcademicValue
from brief_parser.domain.academic_semantics import AcademicRuleScope, AcademicRuleSemantics, AcademicConstraint
from brief_parser.domain.academic_decisions import (
    AcademicDecisionSnapshot, AcademicDecisionRequest, AcademicDecisionEvent, AcademicDecisionEffect,
    AcademicEffectiveRule, AcademicQuestion, content_hash,
)
from brief_parser.validators.academic_decisions import ROLES, typed_property, validate_format_value, validate_answer_scope


class AcademicDecisionError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


@dataclass
class _Working:
    rules: list
    issues: list
    context: object = None
    context_event: object = None
    handled: dict = field(default_factory=dict)
    resolved_reviews: set = field(default_factory=set)
    decided_groups: set = field(default_factory=set)
    relations: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    fragments: list = field(default_factory=list)


def _selector(role, prop, script, scope):
    return "semantic_role" if scope == base_scope(role, prop, script) else "semantic_role_scope"


class AcademicDecisionEngine:
    """Pure replay compiler. The caller owns authentication and atomic storage."""

    def __init__(self, bundle: AcademicParseBundle, *, task_id: str, initial_version_id: str):
        self.bundle = AcademicParseBundle.model_validate_json(bundle.model_dump_json())
        if self.bundle.bundle_version not in {"academic-parse-bundle/1.5", "academic-parse-bundle/1.6"}:
            raise AcademicDecisionError("needs_user_input", "历史解析保持原语义；决策闭环需要新版解析结果。")
        self.task_id, self.initial_version_id = task_id, initial_version_id
        self.source_hash = content_hash(self.bundle.model_dump(mode="json"))
        if self.bundle.bundle_version == "academic-parse-bundle/1.5":
            from brief_parser.compilers import academic_semantic_extractor_v1_4 as semantic_module
        else:
            from brief_parser.compilers import academic_semantic_extractor as semantic_module
        self._semantic_module = semantic_module

    def _refresh(self, work):
        try:
            work.relations, work.conflicts, work.fragments = analyze_rules(work.rules)
        except SemanticAnalysisLimit as error:
            raise AcademicDecisionError("needs_user_input", "回答产生的规则范围组合超出当前分析上限；本次没有发布新快照。") from error
        for index, rule in enumerate(work.rules):
            related = [item for item in work.conflicts if rule.rule_id in item.rule_ids]
            status = ("pending_conflict" if any(item.certainty == "definite" for item in related)
                      else "pending_condition" if related or rule.semantics.condition
                      else "check_only" if rule.semantics.constraint.operator != "eq" or rule.execution_support == "report_only" else "verified")
            work.rules[index] = rule.model_copy(update={"status": status})

    def _bind_rule(self, rule, work):
        condition = rule.semantics.condition
        if not condition or condition.resolution != "known" or work.context is None:
            return rule
        filters = {"medium": axis([work.context.medium])}
        if work.context.channel:
            filters["channel"] = axis([work.context.channel])
        if intersection(rule.semantics.scope, AcademicRuleScope(axes=filters)) is None:
            return None
        scope = AcademicRuleScope(axes={key: value for key, value in rule.semantics.scope.axes.items() if key not in {"medium", "channel"}})
        return rule.model_copy(update={
            "semantics": rule.semantics.model_copy(update={"scope": scope, "condition": None}),
            "target": rule.target.model_copy(update={"selector": _selector(rule.target.semantic_role, rule.property_id, rule.character_scope, scope)}),
            "decision_ids": list(dict.fromkeys(rule.decision_ids + [work.context_event.decision_id])),
        })

    def _baseline(self, context_event=None):
        work = _Working([], list(self.bundle.format_ruleset.issues),
                        context_event.request.answer.submission if context_event else None, context_event)
        for source in self.bundle.format_ruleset.rules:
            support = "typed" if typed_property(source.property_id) else "report_only"
            rule = AcademicEffectiveRule(rule_id=source.rule_id, source_kind="brief_explicit", source_rule_ids=[source.rule_id],
                evidence_refs=source.evidence_refs, observation_ids=[], decision_ids=[], target=source.target,
                property_id=source.property_id, value=source.value, character_scope=source.character_scope,
                semantics=source.semantics, execution_support=support,
                status="check_only" if support == "report_only" and source.status == "verified" else source.status,
                reason="来自已验证的 Brief 解析；执行仍需定位。")
            rule = self._bind_rule(rule, work)
            if rule:
                work.rules.append(rule)
        self._refresh(work)
        return work

    def _question(self, kind, prompt, actions, *, phase="resolve_requirements", **fields):
        question = AcademicQuestion(question_id="pending", kind=kind, phase=phase, prompt=prompt,
                                    allowed_actions=actions, reason=fields.pop("reason", "只按明确的结构化回答更新列出的规则和范围。"), **fields)
        identity = question.model_dump(mode="json", exclude={"question_id", "status", "prompt", "reason", "allowed_actions"})
        return question.model_copy(update={"question_id": stable_id("fmtq", self.source_hash, identity)})

    def _submission_question(self):
        return self._question("submission", "本次使用纸质版、电子版其他渠道，还是系统上传版？", ["set_submission", "skip", "defer"])

    @staticmethod
    def _requires_scope(condition):
        return bool(re.search(r"某章|指定章节|本章|除.+外", condition.original_text)
                    or "范围未" in condition.reason)

    def _scope_for_text(self, refs, prop, role=None, original=None):
        SemanticExtractor = self._semantic_module.AcademicCommonFormatExtractor
        LABELS, EXT_TARGET = self._semantic_module.LABELS, self._semantic_module.EXT_TARGET
        parse_condition = self._semantic_module.parse_condition
        context, candidates = None, []
        for ref in refs:
            found, context = SemanticExtractor().parse_clause(ref, context)
            candidates.extend(item for item in found if item.item.property_id == prop
                              and (role is None or item.item.role == role)
                              and (original is None or item.item.original == original))
        if candidates:
            scopes = [base_scope(item.item.role, prop, item.item.character_scope, item.filters) for item in candidates]
            if all(scope == scopes[0] for scope in scopes):
                chosen = candidates[0]
                condition = chosen.condition or parse_condition(" / ".join(part for ref in refs for part in ref.locator.section_path))[0]
                if condition and condition.resolution == "known":
                    _, filters, _ = parse_condition(condition.original_text)
                    scopes[0] = intersection(scopes[0], AcademicRuleScope(axes=filters))
                return chosen.item.role, scopes[0], chosen.item.character_scope, condition
            return role, None, "all", None
        if role is None:
            for ref in refs:
                _, _, text = parse_condition(ref.quote)
                legacy, extended = _TARGET.match(text), EXT_TARGET.match(text)
                chosen = extended if extended and (not legacy or extended.end() >= legacy.end()) else legacy
                if chosen:
                    role = LABELS[chosen.group()] if chosen is extended else LiteralExtractor._role(chosen.group(1))
                    break
        if role not in ROLES:
            condition, _, _ = parse_condition(" / ".join(ref.quote + " / " + " / ".join(ref.locator.section_path) for ref in refs))
            return None, None, "all", condition
        text = " / ".join(ref.quote + " / " + " / ".join(ref.locator.section_path) for ref in refs)
        script = "latin_digits" if role == "latin_digits" else "latin" if role == "latin_text" else "chinese" if "中文字体" in text or "汉字字体" in text else "all"
        # A named role alone is insufficient to recover chapter, language or
        # exception scope from an unparsed clause. Require explicit applicability.
        from brief_parser.domain.academic_semantics import AcademicCondition
        return role, base_scope(role, prop, script), script, AcademicCondition(original_text=text, resolution="unknown", reason="原文范围未完整解析，补值后仍需确认适用性。")

    @staticmethod
    def _validate_value(prop, value, unit):
        try:
            validate_format_value(prop, value, unit)
        except ValueError as error:
            raise AcademicDecisionError("needs_user_input", str(error)) from error

    def _groups(self, work):
        return build_template_groups(self.bundle.template_layout.observations,
                                     SimpleNamespace(rules=work.rules, issues=work.issues, fragments=work.fragments))

    def _questions(self, work):
        self._refresh(work)
        questions = []
        if work.context is None and any(rule.semantics.condition and rule.semantics.condition.resolution == "known" for rule in work.rules):
            questions.append(self._submission_question())
        for rule in work.rules:
            if rule.semantics.condition and rule.semantics.condition.resolution == "unknown":
                needs_scope = self._requires_scope(rule.semantics.condition)
                questions.append(self._question("condition", f"请确认这条条件要求是否适用于本次论文：{rule.semantics.condition.original_text}",
                    ["confirm_condition", "skip", "defer"], rule_ids=[rule.rule_id], property_id=rule.property_id,
                    semantic_role=rule.target.semantic_role, scope=rule.semantics.scope, requires_scope=needs_scope,
                    reason="确认适用时还须提供明确的类型化对象范围，不能将本章／某章扩大到全文。" if needs_scope else "仅确认当前条件适用性，保留原有对象范围。",
                    evidence_refs=rule.evidence_refs, candidate_values=[rule.value]))
            if rule.semantics.constraint.operator != "eq":
                questions.append(self._question("value", "是否为这条区间／限制选择一个确定格式值？保留约束也可以。", ["clarify_format", "skip", "defer"],
                    rule_ids=[rule.rule_id], property_id=rule.property_id, semantic_role=rule.target.semantic_role, scope=rule.semantics.scope,
                    evidence_refs=rule.evidence_refs, candidate_values=[rule.value]))
        index = {rule.rule_id: rule for rule in work.rules}
        for conflict in work.conflicts:
            rules = [index[identifier] for identifier in conflict.rule_ids]
            # Unknown predicates are settled through applicability first.
            if any(rule.semantics.condition and rule.semantics.condition.resolution == "unknown" for rule in rules):
                continue
            if any(rule.semantics.condition for rule in rules) and work.context is None:
                continue
            questions.append(self._question("conflict", "相交范围上的要求互斥，请选择该范围采用哪条规则。", ["select_rule", "skip", "defer"],
                rule_ids=conflict.rule_ids, property_id=rules[0].property_id, scope=conflict.intersection,
                evidence_refs=list({ref.evidence_id: ref for rule in rules for ref in rule.evidence_refs}.values()), candidate_values=[rule.value for rule in rules]))
        for issue in work.issues:
            refs = [self.bundle.requirement_ir.evidence_index[identifier] for identifier in issue.evidence_ids]
            role, scope, script, condition = self._scope_for_text(refs, issue.property_id or "unclassified.format_property", issue.target.semantic_role if issue.target else None, issue.original_text)
            actions = ["clarify_format", "ignore", "skip", "defer"] if typed_property(issue.property_id) else ["ignore", "skip", "defer"]
            questions.append(self._question("clarification", issue.reason, actions, issue_ids=[issue.source_requirement_id],
                property_id=issue.property_id, semantic_role=role, scope=scope, character_scope=script, condition=condition, evidence_refs=refs))
        represented = {(ref.evidence_id, rule.property_id) for rule in work.rules for ref in rule.evidence_refs}
        represented.update((identifier, issue.property_id) for issue in work.issues for identifier in issue.evidence_ids)
        source_decisions = {item.evidence_id: item for item in self.bundle.source_review.decisions}
        for item in self.bundle.source_review.items:
            if item.kind == "recognized_pending" or item.kind == "unsupported_format":
                continue
            props = [item.property_id] if item.property_id else sorted({prop for identifier in item.evidence_ids for prop in source_decisions[identifier].format_properties}) or [None]
            for prop in props:
                if (item.review_id, prop) in work.resolved_reviews or item.evidence_ids and all((identifier, prop) in represented for identifier in item.evidence_ids):
                    continue
                refs = [self.bundle.requirement_ir.evidence_index[identifier] for identifier in item.evidence_ids]
                role, scope, script, condition = self._scope_for_text(refs, prop or "unclassified.format_property")
                actions = ["clarify_format", "ignore", "skip", "defer"] if typed_property(prop) and refs else ["skip", "defer"]
                questions.append(self._question("source_review", item.reason, actions, review_ids=[item.review_id], property_id=prop,
                                                semantic_role=role, scope=scope, character_scope=script, condition=condition, evidence_refs=refs))
        groups = self._groups(work)
        observations = {item.observation_id: item for item in self.bundle.template_layout.observations}
        categories = {}
        for group in groups:
            if group.group_id in work.decided_groups or group.status in {"covered_by_explicit_rule", "blocked_by_pending_rule"}:
                continue
            # One example per distinct value, plus a few locations. All original
            # observations stay in the immutable source Bundle.
            samples = []
            seen = set()
            for identifier in group.observation_ids:
                item = observations[identifier]
                key = content_hash(item.value)
                if key not in seen or len(samples) < 3:
                    samples.append(item)
                    seen.add(key)
            scope = base_scope(group.semantic_role, group.property_id, group.character_scope)
            if group.status == "needs_template_confirmation":
                categories.setdefault(group.category, []).append((group, samples))
            elif group.status in {"source_mismatch", "inconsistent_observations"}:
                kind = "source_mismatch" if group.status == "source_mismatch" else "template_inconsistent"
                actions = ["keep_brief", "select_template", "skip", "defer"] if kind == "source_mismatch" else ["select_template", "skip", "defer"]
                questions.append(self._question(kind, group.reason + " 选择模板将明确替代列出的相交范围。", actions,
                    rule_ids=group.explicit_rule_ids, group_ids=[group.group_id], property_id=group.property_id,
                    semantic_role=group.semantic_role, scope=scope, category=group.category, observations=samples))
            elif group.status == "unresolved_observation":
                questions.append(self._question("source_review", group.reason, ["skip", "defer"], group_ids=[group.group_id],
                                                property_id=group.property_id, scope=scope, category=group.category, observations=samples))
        for category, entries in sorted(categories.items()):
            questions.append(self._question("template_category", f"是否沿用 Brief 模板中 {category} 类列出的未明确格式属性？", ["accept_template", "reject_template", "skip", "defer"],
                phase="confirm_template", category=category, group_ids=[group.group_id for group, _ in entries], observations=[item for _, items in entries for item in items]))
        current = {}
        for question in questions:
            if question.question_id in work.handled:
                question = work.handled[question.question_id]
            current[question.question_id] = question
        current.update({identifier: item for identifier, item in work.handled.items() if identifier not in current})
        unresolved = any(item.phase == "resolve_requirements" and item.status in {"pending", "deferred"} for item in current.values())
        ordered = []
        priorities = {"submission": 0, "condition": 1, "conflict": 2, "source_mismatch": 3, "template_inconsistent": 4, "value": 5, "clarification": 6, "source_review": 7, "template_category": 8}
        for question in sorted(current.values(), key=lambda item: (priorities[item.kind], item.question_id)):
            if question.phase == "confirm_template" and question.status == "pending" and unresolved:
                question = question.model_copy(update={"status": "blocked", "reason": "先处理条件、冲突和来源差异；暂缓不会默认接受模板。"})
            ordered.append(question)
        return ordered

    def _subtract_rules(self, work, identifiers, scope, decision_id):
        updated = []
        for rule in work.rules:
            if rule.rule_id not in identifiers:
                updated.append(rule)
                continue
            for part in subtract_scope(rule.semantics.scope, scope):
                updated.append(rule.model_copy(update={"rule_id": stable_id("eff", rule.rule_id, part.model_dump(), decision_id),
                    "semantics": rule.semantics.model_copy(update={"scope": part}),
                    "target": rule.target.model_copy(update={"selector": "semantic_role_scope"}),
                    "decision_ids": list(dict.fromkeys(rule.decision_ids + [decision_id]))}))
        work.rules = updated

    def _template_rule(self, group, observation, decision_id):
        if observation.resolution != "resolved" or observation.region != "template_candidate":
            raise AcademicDecisionError("needs_user_input", "未确定或来源不明的观察值不能确认成规则。")
        support = "typed" if typed_property(group.property_id) else "report_only"
        if support == "typed":
            try:
                validate_format_value(group.property_id, observation.value, observation.unit)
            except ValueError:
                support = "report_only"
        scope = base_scope(group.semantic_role, group.property_id, group.character_scope)
        return AcademicEffectiveRule(rule_id=stable_id("efftpl", group.group_id, observation.observation_id, decision_id), source_kind="template_observation_confirmed",
            source_rule_ids=[], evidence_refs=[], observation_ids=[observation.observation_id], decision_ids=[decision_id],
            target=AcademicTarget(object_kind=LiteralExtractor._object_kind(group.semantic_role, group.property_id), semantic_role=group.semantic_role,
                                  selector=_selector(group.semantic_role, group.property_id, group.character_scope, scope)),
            property_id=group.property_id, value=AcademicValue(original_text=str(observation.value), normalized=observation.value, unit=observation.unit,
                                                             dictionary_version="academic-decisions/1.0"), character_scope=group.character_scope,
            semantics=AcademicRuleSemantics(scope=scope, constraint=AcademicConstraint()), execution_support=support,
            status="verified" if support == "typed" else "check_only", reason="用户明确确认 Brief 模板观察；保留 XML 来源，执行仍需论文定位。")

    def _apply(self, work, event, question):
        answer, decision_id = event.request.answer, event.decision_id
        if question.status not in {"pending", "deferred"} or answer.action not in question.allowed_actions:
            raise AcademicDecisionError("needs_user_input", "该问题不可作此回答；请刷新问题及当前适用范围。")
        if answer.action in {"skip", "defer"}:
            work.handled[question.question_id] = question.model_copy(update={"status": "skipped" if answer.action == "skip" else "deferred"})
            return
        if answer.action == "select_rule":
            if answer.selected_id not in question.rule_ids:
                raise AcademicDecisionError("needs_user_input", "只能选择问题中列出的规则。")
            self._subtract_rules(work, set(question.rule_ids) - {answer.selected_id}, question.scope, decision_id)
            work.rules = [rule.model_copy(update={"decision_ids": list(dict.fromkeys(rule.decision_ids + [decision_id]))}) if rule.rule_id == answer.selected_id else rule for rule in work.rules]
        elif answer.action == "confirm_condition":
            identifier = question.rule_ids[0]
            if not answer.applies:
                work.rules = [rule for rule in work.rules if rule.rule_id != identifier]
            else:
                for index, rule in enumerate(work.rules):
                    if rule.rule_id == identifier:
                        if question.requires_scope and answer.scope is None:
                            raise AcademicDecisionError("needs_user_input", "该条件的对象范围尚不明确；确认适用时必须指定类型化范围。")
                        scope = answer.scope or rule.semantics.scope
                        if answer.scope is not None:
                            try:
                                validate_answer_scope(scope)
                                if intersection(rule.semantics.scope, scope) != scope:
                                    raise ValueError("适用范围不能超过原规则对象。")
                                if re.search(r"某章|指定章节|本章", rule.semantics.condition.original_text):
                                    chapter = scope.axes.get("chapter")
                                    excluded = "除" in rule.semantics.condition.original_text and "外" in rule.semantics.condition.original_text
                                    if chapter is None or (not chapter.exclude if excluded else chapter.include is None):
                                        raise ValueError("需要明确章号，不能将某章／本章理解为全部章节。")
                                if re.search(r"除.+外", rule.semantics.condition.original_text) and scope == rule.semantics.scope:
                                    raise ValueError("排除范围未确定，不能确认成原对象的全部范围。")
                            except ValueError as error:
                                raise AcademicDecisionError("needs_user_input", str(error)) from error
                        work.rules[index] = rule.model_copy(update={"semantics": rule.semantics.model_copy(update={"condition": None, "scope": scope}),
                            "target": rule.target.model_copy(update={"selector": _selector(rule.target.semantic_role, rule.property_id, rule.character_scope, scope)}),
                            "decision_ids": rule.decision_ids + [decision_id]})
        elif answer.action in {"accept_template", "select_template", "keep_brief", "reject_template"}:
            groups = {group.group_id: group for group in self._groups(work)}
            observations = {item.observation_id: item for item in self.bundle.template_layout.observations}
            for identifier in question.group_ids:
                group = groups[identifier]
                if answer.action in {"accept_template", "select_template"}:
                    selected = answer.selected_id if answer.action == "select_template" else group.observation_ids[0]
                    if selected not in group.observation_ids or answer.action == "select_template" and selected not in {item.observation_id for item in question.observations}:
                        raise AcademicDecisionError("needs_user_input", "所选观察值不属于这个问题。")
                    rule = self._template_rule(group, observations[selected], decision_id)
                    if answer.action == "select_template":
                        self._subtract_rules(work, set(group.explicit_rule_ids), rule.semantics.scope, decision_id)
                    work.rules.append(rule)
                work.decided_groups.add(identifier)
        elif answer.action == "clarify_format":
            value = answer.format
            if value.property_id != question.property_id or value.semantic_role is not None and question.semantic_role is not None and value.semantic_role != question.semantic_role:
                raise AcademicDecisionError("needs_user_input", "回答不能改变问题的属性或扩大已有目标范围。")
            role = question.semantic_role or value.semantic_role
            if role not in ROLES:
                raise AcademicDecisionError("needs_user_input", "需要选择已注册的论文对象。")
            self._validate_value(value.property_id, value.normalized, value.unit)
            old = next((rule for rule in work.rules if rule.rule_id in question.rule_ids), None)
            script = old.character_scope if old else question.character_scope if question.scope else "latin_digits" if role == "latin_digits" else "latin" if role == "latin_text" else "all"
            if question.scope is not None and value.scope is not None and value.scope != question.scope:
                raise AcademicDecisionError("needs_user_input", "已确定的原文范围不能在补值时更换。")
            scope = question.scope or value.scope
            condition = old.semantics.condition if old else question.condition
            if scope is None:
                raise AcademicDecisionError("needs_user_input", "原文对象范围尚未确定，需要同时明确对象和类型化范围。")
            if question.scope is None:
                try:
                    validate_answer_scope(scope)
                    if intersection(base_scope(role, value.property_id, script), scope) != scope:
                        raise ValueError("用户范围超过所选对象或字符类型。")
                except ValueError as error:
                    raise AcademicDecisionError("needs_user_input", str(error)) from error
                if condition and condition.resolution == "known":
                    _, filters, _ = parse_condition(condition.original_text)
                    scope = intersection(scope, AcademicRuleScope(axes=filters))
            rule = AcademicEffectiveRule(rule_id=stable_id("effuser", question.question_id, decision_id), source_kind="user_decision",
                source_rule_ids=old.source_rule_ids if old else [], evidence_refs=question.evidence_refs, observation_ids=[],
                decision_ids=(old.decision_ids if old else []) + [decision_id], target=AcademicTarget(object_kind=LiteralExtractor._object_kind(role, value.property_id),
                    semantic_role=role, selector=_selector(role, value.property_id, script, scope)), property_id=value.property_id,
                value=AcademicValue(original_text=event.request.raw_answer or str(value.normalized), normalized=value.normalized,
                                    unit=value.unit, dictionary_version="academic-decisions/1.0"), character_scope=script,
                semantics=AcademicRuleSemantics(scope=scope, constraint=AcademicConstraint(), condition=condition),
                status="pending_condition" if condition else "verified", reason="用户给出的类型化格式值已通过属性校验。")
            if old and not compatible(old, rule):
                raise AcademicDecisionError("blocked_conflict", "所选值违反原区间／限制；不能借补值绕过 Brief 要求。")
            if old:
                work.rules = [item for item in work.rules if item.rule_id != old.rule_id]
            rule = self._bind_rule(rule, work)
            if rule:
                work.rules.append(rule)
            work.issues = [issue for issue in work.issues if issue.source_requirement_id not in question.issue_ids]
            work.resolved_reviews.update((identifier, question.property_id) for identifier in question.review_ids)
        elif answer.action == "ignore":
            work.issues = [issue for issue in work.issues if issue.source_requirement_id not in question.issue_ids]
            work.resolved_reviews.update((identifier, question.property_id) for identifier in question.review_ids)
        else:
            raise AcademicDecisionError("needs_user_input", "该回答不适用于当前问题。")
        work.handled[question.question_id] = question.model_copy(update={"status": "answered"})
        self._refresh(work)

    def _replay(self, events, ignored=()):
        if len(events) > 256:
            raise AcademicDecisionError("needs_user_input", "决策历史超出当前会话上限。")
        ids, superseded = set(), set(ignored)
        for event in events:
            if event.task_id != self.task_id or event.source_bundle_sha256 != self.source_hash:
                raise AcademicDecisionError("stale_base_version", "决定引用了其他任务或 Brief 版本。")
            if event.request.supersedes_decision_id:
                previous = next((item for item in events if item.decision_id == event.request.supersedes_decision_id), None)
                if (event.request.supersedes_decision_id not in ids or previous.question_kind != event.question_kind
                        or previous.request.question_id != event.request.question_id):
                    raise AcademicDecisionError("needs_user_input", "被修订的决定无效或问题类型不同。")
                superseded.add(event.request.supersedes_decision_id)
            if event.decision_id in ids:
                raise AcademicDecisionError("needs_user_input", "决策 ID 重复。")
            ids.add(event.decision_id)
        active = [event for event in events if event.decision_id not in superseded]
        contexts = [event for event in active if event.request.answer.action == "set_submission"]
        if len(contexts) > 1:
            raise AcademicDecisionError("blocked_conflict", "修改提交场景必须明确修订旧决定。")
        context_event = contexts[0] if contexts else None
        work, effects = self._baseline(context_event), []
        if context_event:
            if context_event.question_kind != "submission" or context_event.request.question_id != self._submission_question().question_id:
                raise AcademicDecisionError("needs_user_input", "提交场景决定未引用正确问题。")
            work.handled[self._submission_question().question_id] = self._submission_question().model_copy(update={"status": "answered"})
        for event in events:
            if event.decision_id in superseded:
                status, reason = "superseded", "已由明确的新决定修订；历史记录保留。"
            elif event is context_event:
                status, reason = "applied", "已绑定明确的本次提交场景。"
            else:
                question = next((item for item in self._questions(work) if item.question_id == event.request.question_id and item.kind == event.question_kind), None)
                if question is None or question.status not in {"pending", "deferred"}:
                    status, reason = "invalidated", "先前决定的范围、候选或问题顺序已变化；需重新确认。"
                else:
                    self._apply(work, event, question)
                    status, reason = "applied", "结构化回答已经重算为规则或明确的跳过／暂缓状态。"
            effects.append(AcademicDecisionEffect(decision_id=event.decision_id, status=status, reason=reason))
        return work, effects

    def compile(self, events=()) -> AcademicDecisionSnapshot:
        events = list(events)
        work, effects = self._replay(events)
        questions = self._questions(work)
        retained = {identifier for rule in work.rules for identifier in rule.source_rule_ids}
        payload = dict(schema_version="academic-decision-snapshot/1.0", compiler_version="academic-decisions/1.0",
            parent_snapshot_id=events[-1].request.expected_snapshot_id if events else None, revision=len(events), task_id=self.task_id,
            initial_version_id=self.initial_version_id, source_bundle_sha256=self.source_hash, source_artifact_id=self.bundle.manifest.artifact_id,
            source_artifact_version=self.bundle.manifest.artifact_version, domain_pack=self.bundle.requirement_ir.domain_pack,
            submission_context=work.context, events=events, decision_effects=effects, rules=work.rules, issues=work.issues,
            relations=work.relations, conflicts=work.conflicts, fragments=work.fragments, questions=questions,
            excluded_source_rule_ids=sorted({rule.rule_id for rule in self.bundle.format_ruleset.rules} - retained))
        # Use a validated model for canonical defaults, without invoking its hash
        # validator until the full immutable payload has its final content hash.
        provisional = AcademicDecisionSnapshot.model_construct(snapshot_id="0" * 64, **payload)
        encoded = provisional.model_dump(mode="json", exclude={"snapshot_id"})
        return AcademicDecisionSnapshot.model_validate({**encoded, "snapshot_id": content_hash(encoded)})

    def reopen_questions(self, snapshot, decision_id):
        if not any(event.decision_id == decision_id for event in snapshot.events):
            raise AcademicDecisionError("needs_user_input", "需要选择已有决定才能重新回答。")
        if next(effect for effect in snapshot.decision_effects if effect.decision_id == decision_id).status == "superseded":
            raise AcademicDecisionError("stale_base_version", "该决定已经被修订。")
        work, _ = self._replay(snapshot.events, ignored=[decision_id])
        return self._questions(work)

    def submit(self, snapshot, request: AcademicDecisionRequest, *, decision_id: str, created_at: str):
        if self.compile(snapshot.events) != snapshot or request.expected_snapshot_id != snapshot.snapshot_id:
            raise AcademicDecisionError("stale_base_version", "规则快照已变化，请刷新问题。")
        questions = self.reopen_questions(snapshot, request.supersedes_decision_id) if request.supersedes_decision_id else snapshot.questions
        question = next((item for item in questions if item.question_id == request.question_id), None)
        if question is None or question.status not in {"pending", "deferred"} or request.answer.action not in question.allowed_actions:
            raise AcademicDecisionError("needs_user_input", "问题或可选答案已变化，不能提交此决定。")
        if request.supersedes_decision_id:
            previous = next(event for event in snapshot.events if event.decision_id == request.supersedes_decision_id)
            if previous.request.question_id != question.question_id:
                raise AcademicDecisionError("needs_user_input", "修订只能回答原决定对应的问题；其他问题请单独提交。")
        event = AcademicDecisionEvent(decision_id=decision_id, task_id=self.task_id, source_bundle_sha256=self.source_hash,
                                      created_at=created_at, request=request, question_kind=question.kind)
        result = self.compile(snapshot.events + [event])
        if result.decision_effects[-1].status != "applied":
            raise AcademicDecisionError("stale_base_version", "回答所依据的范围已经变化，请重新确认。")
        return result


def render_decision_snapshot(snapshot):
    def safe(value):
        text = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
        for token in ("\\", "`", "*", "_", "[", "]", "|", "#"):
            text = text.replace(token, "\\" + token)
        return text
    lines = ["# Brief 解析决策报告", "", snapshot.scope_note, "", f"规则快照：{snapshot.snapshot_id}；修订：{snapshot.revision}", ""]
    observations = {item.observation_id: item for question in snapshot.questions for item in question.observations}
    for rule in snapshot.rules:
        lines.append(f"- {safe(rule.status)}：{safe(rule.target.semantic_role)} / {safe(rule.property_id)}，{safe(rule.value.normalized)} {safe(rule.value.unit or '')}")
        lines.append("  - 范围：" + safe(rule.semantics.scope.model_dump()) + "；决定：" + safe(rule.decision_ids))
        for ref in rule.evidence_refs:
            lines.append("  - Brief 原文：" + safe(ref.quote) + "；位置：" + safe(ref.locator.model_dump(exclude_none=True)))
        for identifier in rule.observation_ids:
            item = observations.get(identifier)
            lines.append("  - 模板观察：" + safe(identifier) + ("；XML 位置：" + safe(item.location.model_dump(exclude_none=True)) if item else "；完整 XML 来源保留在原始 Bundle。"))
    for fragment in snapshot.fragments:
        if fragment.status == "verified":
            lines.append("- 可供后续定位的范围分片：" + safe(fragment.rule_id) + "；" + safe(fragment.scope.model_dump()))
    events = {event.decision_id: event for event in snapshot.events}
    for effect in snapshot.decision_effects:
        event = events[effect.decision_id]
        lines.append(f"- 决定 {safe(effect.decision_id)}：{safe(event.request.answer.action)} / {safe(effect.status)}；{safe(effect.reason)}")
    for question in snapshot.questions:
        if question.status in {"pending", "blocked", "deferred", "skipped"}:
            lines.append(f"- {safe(question.status)}：{safe(question.prompt)}；{safe(question.reason)}")
            for ref in question.evidence_refs:
                lines.append("  - 原文：" + safe(ref.quote) + "；位置：" + safe(ref.locator.model_dump(exclude_none=True)))
    return "\n".join(lines) + "\n"
