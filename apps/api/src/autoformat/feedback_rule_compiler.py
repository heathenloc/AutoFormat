"""Compile trusted scopes into bounded Word-object/UTF-16 fragments.

Only explicit conflict choices remove an overlapping requirement. Nothing in
this module edits Word or treats feedback recency as an implicit priority.
"""
from __future__ import annotations

from types import SimpleNamespace

from brief_parser.compilers.academic_scope import CHARACTERS, compatible
from .feedback_contracts import FormatValue, content_hash, seal_contract, property_minimum_unit
from .feedback_rules_contracts import (FeedbackCompiledRule, FeedbackRuleSpan,
    FeedbackRuleFragment, FeedbackRuleConflictReview, FeedbackRulesSnapshot)
from .feedback_scope import character_kind
from .feedback_store import FeedbackError


def _id(prefix, value):
    return prefix + content_hash(value)[:32]


def _range(span):
    return (span.start_utf16, span.start_utf16 + span.length_utf16) if span.start_utf16 is not None else (None, None)


def _overlap(a, b):
    if a.object_id != b.object_id: return None
    x, y = _range(a), _range(b)
    if x[0] is None or y[0] is None:
        return a if y[0] is None else b
    lo, hi = max(x[0], y[0]), min(x[1], y[1])
    return FeedbackRuleSpan(object_id=a.object_id, start_utf16=lo, length_utf16=hi-lo) if lo < hi else None


def _subtract(span, cut):
    if span.start_utf16 is None: return []
    lo, hi = _range(span); left, right = _range(cut)
    return [FeedbackRuleSpan(object_id=span.object_id, start_utf16=x, length_utf16=y-x)
        for x, y in [(lo, left), (right, hi)] if x < y]


def _scripts(scope, script="all"):
    values = set(CHARACTERS if script == "all" else [script])
    axis = scope.axes.get("characters") if scope else None
    if axis:
        if axis.include is not None: values.intersection_update(axis.include)
        values.difference_update(axis.exclude)
    return values


def _matches(obj, scope):
    values = {"roles": obj.semantic_role, "object_language": obj.object_language,
        "regions": obj.region, "region_zone": obj.region_zone, "chapter": obj.chapter,
        "object_ordinal": obj.object_ordinal}
    for name, axis in scope.axes.items():
        if name in {"characters", "property_component"}: continue
        if name not in values: return None  # never discard an unknown restriction
        if values[name] in axis.exclude or axis.include is not None and values[name] not in axis.include: return False
    return True


def _characters(object_id, text, scripts, clips=None):
    ranges, offset, start = [], 0, None
    for char in text:
        size = len(char.encode("utf-16-le")) // 2
        eligible = character_kind(char) in scripts
        if eligible and start is None: start = offset
        if not eligible and start is not None:
            ranges.append(FeedbackRuleSpan(object_id=object_id, start_utf16=start, length_utf16=offset-start)); start = None
        offset += size
    if start is not None: ranges.append(FeedbackRuleSpan(object_id=object_id, start_utf16=start, length_utf16=offset-start))
    if clips is not None:
        ranges = [common for span in ranges for clip in clips if (common := _overlap(span, clip)) is not None]
    # Adjacent/multi-span selection ranges are normalized, never counted twice.
    result = []
    for span in sorted(ranges, key=lambda s: s.start_utf16):
        if result and span.start_utf16 <= _range(result[-1])[1]:
            previous = result.pop(); end = max(_range(previous)[1], _range(span)[1])
            span = FeedbackRuleSpan(object_id=object_id, start_utf16=previous.start_utf16, length_utf16=end-previous.start_utf16)
        result.append(span)
    return result


def _properties(prop, scope=None):
    if prop != "page.margin.all": return [prop]
    axis = scope.axes.get("property_component") if scope else None
    return ["page.margin." + side for side in ["top", "bottom", "left", "right"]
        if axis is None or side not in axis.exclude and (axis.include is None or side in axis.include)]


def _compatible(a, b):
    constraint = SimpleNamespace(operator="eq")
    return compatible(SimpleNamespace(property_id=a["property_id"], value=a["value"], semantics=SimpleNamespace(constraint=constraint)),
        SimpleNamespace(property_id=b["property_id"], value=b["value"], semantics=SimpleNamespace(constraint=constraint)))


def _cut(pieces, rule_id, prop, cuts, status, conflict_id, decision_id=None):
    result = []
    by_object = {}
    for cut in cuts: by_object.setdefault(cut.object_id, []).append(cut)
    for piece in pieces:
        remaining = [piece]
        if piece["rule_id"] == rule_id and piece["property_id"] == prop and piece["status"] != "superseded":
            for cut in by_object.get(piece["span"].object_id, []):
                next_remaining = []
                for item in remaining:
                    common = _overlap(item["span"], cut)
                    if common is None: next_remaining.append(item); continue
                    next_remaining.extend({**item, "span": rest} for rest in _subtract(item["span"], common))
                    changed = {**item, "span": common, "status": status,
                        "conflict_ids": sorted(set(item["conflict_ids"] + [conflict_id])),
                        "decision_ids": sorted(set(item["decision_ids"] + ([decision_id] if decision_id else [])))}
                    result.append(changed)
                remaining = next_remaining
        result.extend(remaining)
    return result


def compile_rules(context, inputs, basis, text, semantic, decisions, *, revision,
                  previous_snapshot_id, fingerprint, parent_snapshot_id=None, raw_texts=None, inherited=None,
                  compiler_version="feedback-rules/1.1", inherited_mapping=None):
    """Inputs and decisions have already been source-replayed by the store."""
    objects = {o.object_id: o for o in semantic.objects} if semantic else {}
    paragraphs = {p.object_id: p for p in text.paragraphs} if text else {}
    rules, pieces, conflicts, pending = [], [], [], []
    used_decisions = set()
    rebased = inherited is not None and compiler_version == "feedback-rules/1.2"
    if rebased:
        rules.extend(inherited.rules)
        for fragment in inherited.fragments:
            if fragment.status == "superseded": continue
            mapped = (inherited_mapping or {}).get(fragment.span.object_id)
            span = fragment.span.model_copy(update={"object_id": mapped}) if mapped else fragment.span
            pieces.append({**fragment.model_dump(exclude={"fragment_id", "span", "value"}),
                "span": span, "value": fragment.value,
                "status": fragment.status if mapped else "pending_target", "conflict_ids": [], "decision_ids": []})
    elif inherited:
        # A child DOCX needs fresh target mapping before inherited local
        # exceptions can execute. Retain provenance but grant no target trust.
        for rule in inherited.rules:
            if rule.source_kind == "feedback": rules.append(rule)
        inherited_ids = {r.rule_id for r in rules}
        for fragment in inherited.fragments:
            if fragment.rule_id in inherited_ids and fragment.status != "superseded":
                pieces.append({**fragment.model_dump(exclude={"fragment_id", "span", "value"}),
                    "span": fragment.span, "value": fragment.value, "status": "pending_target", "conflict_ids": [], "decision_ids": []})
    def add_piece(rule, prop, span, status):
        pieces.append(dict(rule_id=rule.rule_id, property_id=prop, span=span, value=rule.value,
            status=status, conflict_ids=[], decision_ids=[]))
        if len(pieces) > 20000: raise FeedbackError("needs_user_input", "规则分片过多，请缩小或拆分反馈。")

    if basis and not rebased:
        grouped = {}
        for fragment in basis.fragments: grouped.setdefault(fragment.rule_id, []).append(fragment)
        for source in basis.rules:
            rule = FeedbackCompiledRule(rule_id=_id("academic:", source.rule_id), source_kind="academic",
                source_rule_id=source.rule_id, origin_version_id=context.base_version_id,
                property_id=source.property_id, value=FormatValue(normalized=source.value.normalized, unit=source.value.unit),
                original_requirement=source.value.original_text or source.reason,
                evidence_quotes=[e.quote for e in source.evidence_refs], requested_scope="document")
            rules.append(rule)
            scopes = grouped.get(source.rule_id, [])
            if not scopes:  # a selected source must expose its compiler fragments
                raise FeedbackError("validation_failed", "学术规则缺少可重放的范围分片。")
            minimum = property_minimum_unit(source.property_id)
            kind = {"section": "section", "table": "table"}.get(minimum, "paragraph")
            for fragment in scopes:
                for obj in objects.values():
                    if obj.kind != kind: continue
                    match = _matches(obj, fragment.scope)
                    if match is False: continue
                    status = "verified" if fragment.status == "verified" and match is True and source.execution_support == "typed" else "pending_basis"
                    if minimum in {"field_or_object", "region"}: status = "pending_target"
                    characters = fragment.scope.axes.get("characters")
                    unknown_scripts = characters and not set((characters.include or []) + characters.exclude) <= set(CHARACTERS)
                    if unknown_scripts: status = "pending_basis"
                    if obj.requires_manual_targeting or obj.kind == "paragraph" and (obj.object_id not in paragraphs or not paragraphs[obj.object_id].editable): status = "pending_target"
                    spans = _characters(obj.object_id, paragraphs[obj.object_id].text, set(CHARACTERS) if unknown_scripts else _scripts(fragment.scope)) if source.property_id.startswith("font.") and obj.object_id in paragraphs else [FeedbackRuleSpan(object_id=obj.object_id)]
                    for prop in _properties(source.property_id, fragment.scope):
                        for span in spans: add_piece(rule, prop, span, status)

    for analysis in inputs:
        parsed = analysis.interpretation
        if parsed.kind != "new_rule":
            if parsed.kind == "clarification_needed": pending.append(parsed.feedback_id)
            continue
        for candidate in parsed.candidates:
            review = next((s for s in parsed.scope_reviews if s.candidate_id == candidate.candidate_id), None)
            anchor = analysis.selection.anchor if analysis.selection else None
            rule = FeedbackCompiledRule(rule_id=_id("feedback:", [parsed.feedback_id, candidate.candidate_id]),
                source_kind="feedback", source_rule_id=candidate.candidate_id, feedback_id=parsed.feedback_id,
                candidate_id=candidate.candidate_id, origin_version_id=context.base_version_id,
                property_id=candidate.property_id, value=candidate.value, original_requirement=(raw_texts or {}).get(parsed.feedback_id, parsed.reason),
                evidence_quotes=[], requested_scope=candidate.requested_scope, anchor=anchor)
            rules.append(rule)
            if review is None:
                pending.append(parsed.feedback_id); continue
            status = "verified"
            if not basis: status = "pending_basis"
            elif review.requires_confirmation and review.review_id not in analysis.confirmed_review_ids: status = "pending_scope"
            incoming = []
            for target_id in review.target_ids:
                obj = objects.get(target_id)
                if obj is None: raise FeedbackError("validation_failed", "规则范围对象不在此版本中。")
                clips = None
                if candidate.requested_scope == "selection" and candidate.property_id.startswith("font."):
                    if anchor is None: raise FeedbackError("validation_failed", "文字规则没有可信选区锚点。")
                    clips = [FeedbackRuleSpan(object_id=r.object_id, start_utf16=r.start_utf16, length_utf16=r.length_utf16) for r in anchor.ranges if r.object_id == target_id]
                spans = _characters(target_id, paragraphs[target_id].text, _scripts(candidate.applicability_scope, candidate.character_scope), clips) if candidate.property_id.startswith("font.") else [FeedbackRuleSpan(object_id=target_id)]
                for prop in _properties(candidate.property_id, candidate.applicability_scope):
                    for span in spans:
                        incoming.append(dict(rule_id=rule.rule_id, property_id=prop, span=span,
                            value=rule.value, status=status, conflict_ids=[], decision_ids=[]))
            # Scope confirmation precedes conflict choices. Pending requirements
            # remain visible, and cannot grant override authority.
            if status == "verified":
                pairs, blocked, old_index = {}, {}, {}
                for old in pieces:
                    if old["status"] != "superseded":
                        old_index.setdefault((old["property_id"], old["span"].object_id), []).append(old)
                for new in incoming:
                    for old in old_index.get((new["property_id"], new["span"].object_id), []):
                        common = _overlap(old["span"], new["span"])
                        if common is None: continue
                        if old["status"] in {"pending_basis", "pending_target", "pending_scope"}:
                            blocked.setdefault(new["property_id"], []).append(common)
                        elif not _compatible(old, new):
                            pairs.setdefault((old["rule_id"], new["property_id"]), []).append(common)
                for prop, spans in blocked.items():
                    incoming = _cut(incoming, rule.rule_id, prop, spans, "pending_basis", "basis-unresolved")
                for (old_id, prop), spans in sorted(pairs.items()):
                    unique = {content_hash(s.model_dump(mode="json")): s for s in spans}
                    spans = sorted(unique.values(), key=lambda s: (s.object_id, s.start_utf16 or 0, s.length_utf16 or 0))
                    if len(spans) > 5000: raise FeedbackError("needs_user_input", "单项冲突的文字范围过多，请拆分反馈。")
                    conflict_id = _id("conflict:", [rule.rule_id, old_id, prop, [s.model_dump(mode="json") for s in spans]])
                    allowed = ["keep_rule", "local_exception" if review.effective_scope in {"selection", "paragraph"} else "update_rule"]
                    decision = decisions.get(conflict_id)
                    action, decision_id = (decision[0].action, decision[1]) if decision else (None, None)
                    if action and action not in allowed: raise FeedbackError("validation_failed", "历史决定超出了已确认的实际范围。")
                    if decision: used_decisions.add(decision_id)
                    conflicts.append(FeedbackRuleConflictReview(conflict_id=conflict_id, feedback_id=parsed.feedback_id,
                        candidate_id=candidate.candidate_id, incoming_rule_id=rule.rule_id, existing_rule_id=old_id,
                        property_id=prop, spans=spans, allowed_actions=allowed, resolution=action, decision_id=decision_id,
                        reason="相同对象、属性和字符范围上的格式要求不能同时满足；没有默认优先级。"))
                    if action == "keep_rule":
                        incoming = _cut(incoming, rule.rule_id, prop, spans, "superseded", conflict_id, decision_id)
                    elif action:
                        pieces = _cut(pieces, old_id, prop, spans, "superseded", conflict_id, decision_id)
                    else:
                        incoming = _cut(incoming, rule.rule_id, prop, spans, "pending_conflict", conflict_id)
                        pieces = _cut(pieces, old_id, prop, spans, "pending_conflict", conflict_id)
            pieces.extend(incoming)
            if len(pieces) > 20000 or len(conflicts) > 256 or len(rules) > 1024 or sum(c.feedback_id == parsed.feedback_id for c in conflicts) > 64:
                raise FeedbackError("needs_user_input", "规则或冲突过多，请拆分反馈。")

    fragments = []
    for piece in pieces:
        fragments.append(seal_contract(FeedbackRuleFragment, {**piece, "span": piece["span"].model_dump(mode="json"),
            "value": piece["value"].model_dump(mode="json")}, "fragment_id"))
    fragments = list({f.fragment_id: f for f in fragments}.values())
    pending = sorted(set(pending))
    has_feedback = any(r.source_kind == "feedback" for r in rules)
    blocked = not basis or pending or any(f.status.startswith("pending_") for f in fragments)
    status = "no_rule_change" if not has_feedback and not pending else "needs_user_input" if blocked else "ready"
    ordered_decisions = sorted(decisions.values(), key=lambda d: d[1])
    decision_ids = [d[1] for d in ordered_decisions]
    from .feedback_rules_contracts import FeedbackRulesSnapshotV2
    model = FeedbackRulesSnapshotV2 if compiler_version == "feedback-rules/1.2" else FeedbackRulesSnapshot
    return seal_contract(model, dict(schema_version="feedback-rule-snapshot/1.2" if compiler_version == "feedback-rules/1.2" else "feedback-rule-snapshot/1.1",
        task_id=context.task_id, base_version_id=context.base_version_id, base_docx_sha256=context.base_docx_sha256,
        version_context_id=context.context_id, brief_version_id=context.brief_version_id,
        academic_rules_snapshot_id=context.rules_snapshot_id, parent_snapshot_id=parent_snapshot_id,
        previous_snapshot_id=previous_snapshot_id, revision=revision, engine_fingerprint=fingerprint,
        basis_available=basis is not None, inputs=inputs, rules=rules, fragments=fragments, conflicts=conflicts,
        decision_ids=decision_ids, decision_requests=[d[0] for d in ordered_decisions],
        invalidated_decision_ids=sorted(set(decision_ids)-used_decisions), pending_feedback_ids=pending,
        status=status, reason="规则片段已编译并保留来源与决定；尚未修改论文。" if not blocked else
            "仍有范围、冲突或来源依据待确认；对应片段不能用于编辑，尚未修改论文。"), "snapshot_id")
