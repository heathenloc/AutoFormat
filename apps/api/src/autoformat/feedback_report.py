"""Append verified per-fragment outcomes without rewriting report history."""
from .feedback_store import FeedbackError
from .feedback_processing import FeedbackProcessor
from .selection_store import SelectionStore


def feedback_report_facts(snapshot, result, basis, feedback_store, previous):
    rules = {r.rule_id: r for r in snapshot.rules}
    academic = {r.rule_id: r for r in basis.rules}
    facts, changes = [], []
    decisions = list(previous.get("decisions", []))
    known = {d["decision_id"] for d in decisions}
    input_choices = {}
    for analysis in snapshot.inputs:
        feedback_id = analysis.interpretation.feedback_id
        with feedback_store.versions._transaction() as connection:
            target = connection.execute("SELECT * FROM selection_target_decisions WHERE feedback_id=?", (feedback_id,)).fetchone()
            rows = connection.execute("SELECT * FROM feedback_processing_decisions WHERE feedback_id=? ORDER BY sequence", (feedback_id,)).fetchall()
        sources = []
        if target:
            answer = SelectionStore._decision(target)
            sources.append((target["decision_id"], answer.raw_answer, "confirm_target"))
        for row in rows:
            answer = FeedbackProcessor._answer(row)
            sources.append((row["decision_id"], answer.raw_answer or answer.answer.model_dump_json(), answer.answer.action))
        for identifier, raw, action in sources:
            input_choices[feedback_id] = identifier
            if identifier not in known:
                decisions.append(dict(decision_id=identifier, question_id=feedback_id, raw_answer=raw, normalized_choice=action))
                known.add(identifier)
    for decision_id, request in zip(snapshot.decision_ids, snapshot.decision_requests):
        if decision_id not in known:
            decisions.append(dict(decision_id=decision_id, question_id=request.conflict_id,
                raw_answer=request.raw_answer, normalized_choice=request.action))
            known.add(decision_id)
    for fragment in snapshot.fragments:
        if fragment.status != "verified": continue
        ops = [o for o in result["operations"] if o["fragment_id"] == fragment.fragment_id]
        if not ops: raise FeedbackError("validation_failed", "规则分片缺少执行校验结果。")
        rule = rules[fragment.rule_id]
        decision_id = None
        if rule.source_kind == "feedback":
            record = feedback_store.get(snapshot.task_id, rule.origin_version_id, rule.feedback_id)
            source_id, source_version, kind = record.feedback_id, rule.origin_version_id, "user_feedback"
            decision_id = "submission:" + record.feedback_id
            if decision_id not in known:
                decisions.append(dict(decision_id=decision_id, question_id=record.feedback_id,
                    raw_answer=record.submission.raw_text, normalized_choice="submit_typed_feedback"))
                known.add(decision_id)
            decision_id = input_choices.get(record.feedback_id, decision_id)
            winners = [c.decision_id for c in snapshot.conflicts if c.incoming_rule_id == rule.rule_id and c.resolution in {"local_exception", "update_rule"}]
            if winners: decision_id = winners[-1]
            evidence = [dict(source_artifact_id=source_id, source_version=source_version,
                locator="feedback:" + record.feedback_id, quote=record.submission.raw_text)]
            role = "selected_object"
        else:
            source = academic[rule.source_rule_id]
            kind = "user_feedback" if source.source_kind == "user_decision" else source.source_kind
            source_id, source_version = "brief:" + snapshot.brief_version_id, snapshot.brief_version_id
            evidence = [dict(source_artifact_id=source_id, source_version=source_version,
                locator=str(ref.locator.model_dump(mode="json")), quote=ref.quote) for ref in source.evidence_refs]
            if not evidence:
                evidence = [dict(source_artifact_id=source_id, source_version=source_version,
                    locator="confirmed observation:" + ",".join(source.observation_ids), quote=source.value.original_text)]
            role = source.target.semantic_role
            decision_id = source.decision_ids[-1] if source.decision_ids else None
            if decision_id is not None and decision_id not in known:
                raise FeedbackError("validation_failed", "学术规则的原始决定未保留在父版本报告中。")
        identifier = "feedback-result:" + snapshot.base_version_id + ":" + fragment.fragment_id
        status = "modified_verified" if any(o["changed"] for o in ops) else "already_satisfied"
        fact = dict(rule_id=identifier, source_kind=kind, source_artifact_id=source_id,
            source_version=source_version, original_requirement=rule.original_requirement, evidence_refs=evidence,
            object_id=fragment.span.object_id, semantic_role=role, property_id=fragment.property_id,
            requested_scope=rule.requested_scope,
            effective_scope="selection" if fragment.span.start_utf16 is not None else
                "paragraph" if fragment.property_id.startswith("paragraph.") else
                "same_kind" if fragment.property_id == "table.border_style" and rule.requested_scope in {"selection", "paragraph"} else
                rule.requested_scope if fragment.property_id == "table.border_style" else "document",
            before_value={"operations": [{"xml_path": o["xml_path"], "characters": o["character_type"], "value": o["before"]} for o in ops]},
            after_value={"value": fragment.value.normalized, "unit": fragment.value.unit,
                "span": fragment.span.model_dump(mode="json"), "operations": ops},
            status=status, reason="逐目标格式回读、正文和受保护结构及 Open XML 校验通过。",
            next_action=None, decision_id=decision_id,
            verification_ref="feedback-edit-result:" + snapshot.snapshot_id + ":" + fragment.fragment_id)
        facts.append(fact)
        if status == "modified_verified":
            changes.append(dict(change_id="change:" + identifier, rule_id=identifier,
                object_id=fact["object_id"], property_id=fact["property_id"], effective_scope=fact["effective_scope"],
                before_value=fact["before_value"], after_value=fact["after_value"],
                validation_status="verified", verification_ref=fact["verification_ref"]))
    return [*previous.get("rules", []), *facts], changes, decisions
