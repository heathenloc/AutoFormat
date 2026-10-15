"""Object-range conflict choices, immutable snapshots and source replay."""
import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from brief_parser.compilers.academic_scope import analyze_rules, base_scope
from brief_parser.domain.academic_decisions import AcademicEffectiveRule
from autoformat.feedback_contracts import content_hash, canonical_bytes
from autoformat.feedback_processing import FeedbackProcessor
from autoformat.feedback_rules_contracts import FeedbackRuleBasis, FeedbackRulesDecision
from autoformat.feedback_rules_store import FeedbackRulesStore
from autoformat.feedback_store import FeedbackError, FeedbackStore
from autoformat.local_api import create_local_api
from autoformat.rule_snapshots import RuleSnapshotStore
from autoformat.version_store import VersionStore, new_id
from conftest import publish_fixture, submission_for
from test_processing import saved, confirm_for
from test_selection import indexes, custom_task, answer_for


def academic_rule(prop="font.size", value=12, unit="pt", role="document_text", script="all", key="brief-size"):
    quote = f"{prop}={value}"
    return AcademicEffectiveRule.model_validate(dict(rule_id=key, source_kind="brief_explicit", source_rule_ids=[key],
        evidence_refs=[dict(evidence_id="e-"+key, source_id="brief", block_id="block-1", start=0, end=len(quote),
            quote=quote, quote_sha256=sha256(quote.encode()).hexdigest(), locator={}, match_status="exact")],
        observation_ids=[], decision_ids=[], target=dict(object_kind="paragraph", semantic_role=role, selector="semantic_role"),
        property_id=prop, value=dict(original_text=quote, normalized=value, unit=unit, dictionary_version="test/1.0"),
        character_scope=script, semantics=dict(scope=base_scope(role, prop, script).model_dump(), constraint={"operator":"eq"}),
        status="verified", reason="Verified fixture requirement."))


def basis_for(context, rules=()):
    return FeedbackRuleBasis(academic_rules_snapshot_id=context.rules_snapshot_id, rules=list(rules), fragments=analyze_rules(rules)[2])


def rules_store(feedback, indexes, rules=()):
    return FeedbackRulesStore(FeedbackProcessor(feedback, indexes), basis_loader=lambda c: basis_for(c, rules))


def decision_for(review, context, action, **updates):
    data = dict(schema_version="feedback-decision-request/1.1", request_id=new_id(), task_id=context.task_id,
        base_version_id=context.base_version_id, expected_base_docx_sha256=context.base_docx_sha256,
        expected_context_id=context.context_id, feedback_id=review.parse_result.feedback_id,
        expected_parse_result_id=review.parse_result.result_id, expected_snapshot_id=review.snapshot.snapshot_id,
        conflict_id=next(c.conflict_id for c in review.snapshot.conflicts if c.feedback_id == review.parse_result.feedback_id and c.resolution is None),
        action=action, raw_answer="确认当前展示的冲突选择")
    data.update(updates)
    return FeedbackRulesDecision.model_validate(data)


@pytest.mark.parametrize("action", ["keep_rule", "local_exception"])
def test_local_conflict_only_blocks_and_replaces_the_intersection(feedback_env, indexes, action):
    versions, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    context = feedback.context(v1.task_id, v1.version_id)
    hint = submission_for(context).selection.model_dump(mode="json")
    hint["selected_text"] = "Selectable"; hint["spans"][0]["end_offset_utf16"] = 10
    receipt, context, _ = saved(feedback, v1, "字号14pt", selection=hint)
    before = {k: versions.artifact_path(v1.task_id, v1.version_id, k).read_bytes() for k in ["docx", "preview", "report_json"]}
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    snapshot = review.snapshot
    assert snapshot.status == "needs_user_input" and len(snapshot.conflicts) == 1
    conflict = snapshot.conflicts[0]
    assert (conflict.spans[0].start_utf16, conflict.spans[0].length_utf16) == (0, 10)
    assert conflict.allowed_actions == ["keep_rule", "local_exception"]
    old_id = conflict.existing_rule_id
    assert any(f.rule_id == old_id and f.status == "verified" and f.span.start_utf16 == 10 and f.span.length_utf16 == 13 for f in snapshot.fragments)
    answer = decision_for(review, context, action)
    after = store.decide(v1.task_id, v1.version_id, receipt.feedback_id, answer)
    assert after.snapshot.status == "ready"
    active = [f for f in after.snapshot.fragments if f.status == "verified" and f.span.start_utf16 == 0]
    assert len(active) == 1 and active[0].value.normalized == (12 if action == "keep_rule" else 14)
    assert store.load(v1.task_id, v1.version_id, snapshot.snapshot_id) == snapshot
    assert store.decide(v1.task_id, v1.version_id, receipt.feedback_id, answer) == after
    restarted = rules_store(FeedbackStore(VersionStore(versions.root)), indexes, [academic_rule()])
    assert restarted.load(v1.task_id, v1.version_id) == after.snapshot
    assert {k: versions.artifact_path(v1.task_id, v1.version_id, k).read_bytes() for k in before} == before
    assert len(versions.list_versions(v1.task_id)) == 2


def test_global_update_needs_scope_confirmation_and_history_keeps_old_input(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "全文字号14pt", selection=None, requested_scope="document")
    pending = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert not pending.snapshot.conflicts
    assert any(f.status == "pending_scope" for f in pending.snapshot.fragments)
    analysis = store.processor.get(v1.task_id, v1.version_id, receipt.feedback_id)
    store.processor.confirm(v1.task_id, v1.version_id, receipt.feedback_id, confirm_for(analysis, context,
        dict(action="confirm_scope", accepted_review_ids=[r.review_id for r in analysis.interpretation.scope_reviews])))
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert review.snapshot.conflicts[0].allowed_actions == ["keep_rule", "update_rule"]
    with pytest.raises(FeedbackError): store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, "local_exception"))
    final = store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, "update_rule"))
    assert final.snapshot.status == "ready"
    assert store.load(v1.task_id, v1.version_id, pending.snapshot.snapshot_id) == pending.snapshot
    assert all(f.value.normalized == 14 for f in final.snapshot.fragments if f.status == "verified")


def test_unit_equivalence_and_margin_component_intersection(feedback_env, indexes):
    _, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule("page.margin.top", 2.5, "cm")])
    receipt, context, _ = saved(feedback, v1, "全文页边距25mm", requested_scope="document", selection=None)
    analysis = store.processor.get(v1.task_id, v1.version_id, receipt.feedback_id)
    store.processor.confirm(v1.task_id, v1.version_id, receipt.feedback_id, confirm_for(analysis, context,
        dict(action="confirm_scope", accepted_review_ids=[r.review_id for r in analysis.interpretation.scope_reviews])))
    equal = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert equal.snapshot.status == "ready" and not equal.snapshot.conflicts
    second, _, _ = saved(feedback, v1, "全文上页边距3cm", requested_scope="document", selection=None)
    a = store.processor.get(v1.task_id, v1.version_id, second.feedback_id)
    store.processor.confirm(v1.task_id, v1.version_id, second.feedback_id, confirm_for(a, context,
        dict(action="confirm_scope", accepted_review_ids=[r.review_id for r in a.interpretation.scope_reviews])))
    review = store.review(v1.task_id, v1.version_id, second.feedback_id)
    assert len(review.snapshot.conflicts) == 2
    assert all(c.property_id == "page.margin.top" for c in review.snapshot.conflicts)
    assert {f.property_id for f in review.snapshot.fragments if f.status == "verified"} >= {"page.margin.left", "page.margin.right", "page.margin.bottom"}


def test_unknown_basis_never_becomes_an_empty_verified_basis(feedback_env, indexes):
    _, feedback, _, v1, _ = feedback_env
    store = FeedbackRulesStore(FeedbackProcessor(feedback, indexes), basis_loader=lambda _: None)
    receipt, _, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert not review.snapshot.basis_available and review.snapshot.status == "needs_user_input"
    assert {f.status for f in review.snapshot.fragments} == {"pending_basis"}


def test_report_only_basis_is_retained_and_cannot_be_silently_overridden(feedback_env, indexes):
    _, feedback, _, v1, _ = feedback_env
    source = academic_rule().model_copy(update={"execution_support": "report_only", "status": "check_only"})
    store = rules_store(feedback, indexes, [source])
    receipt, _, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert len(review.snapshot.rules) == 2 and review.snapshot.status == "needs_user_input"
    assert {f.status for f in review.snapshot.fragments} == {"pending_basis"}
    assert not review.snapshot.conflicts


def test_saved_feedbacks_conflict_without_default_recency_priority(feedback_env, indexes):
    _, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes)
    one, context, _ = saved(feedback, v1, "字号12pt")
    initial = store.review(v1.task_id, v1.version_id, one.feedback_id)
    assert initial.snapshot.status == "ready"
    two, _, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, two.feedback_id)
    assert len(review.snapshot.conflicts) == 1
    assert {f.status for f in review.snapshot.fragments} == {"pending_conflict"}
    answer = decision_for(review, context, "local_exception")
    after = store.decide(v1.task_id, v1.version_id, two.feedback_id, answer)
    assert after.snapshot.status == "ready"
    # A new version has no implicit dependency on an unpublished parent head.
    publish_fixture(store.versions, v1, feedback.versions.root.parent / "v2")
    assert store.decide(v1.task_id, v1.version_id, two.feedback_id, answer) == after
    with pytest.raises(FeedbackError): store.decide(v1.task_id, v1.version_id, two.feedback_id,
        answer.model_copy(update={"request_id": new_id()}))


def test_tampering_snapshot_and_updating_checksums_cannot_fake_a_verified_rule(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, _, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    payload = review.snapshot.model_dump(mode="json")
    payload["reason"] = "Forged but checksum-valid snapshot"
    payload["snapshot_id"] = content_hash({k:v for k,v in payload.items() if k != "snapshot_id"})
    with versions._transaction() as connection:
        connection.execute("UPDATE feedback_rules_snapshots SET snapshot_id=?,payload_json=?,payload_sha256=? WHERE snapshot_id=?",
            (payload["snapshot_id"], canonical_bytes(payload).decode(), content_hash(payload), review.snapshot.snapshot_id))
    with pytest.raises(FeedbackError, match="重放"): store.load(v1.task_id, v1.version_id, payload["snapshot_id"])


def test_concurrent_choices_only_one_can_advance_head(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    first = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    review = first.review(v1.task_id, v1.version_id, receipt.feedback_id)
    second = rules_store(FeedbackStore(VersionStore(versions.root)), indexes, [academic_rule()])
    barrier = Barrier(2)
    def choose(store, action):
        original = store._append
        def race(*a, **k): barrier.wait(timeout=30); return original(*a, **k)
        store._append = race
        try: return store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, action)).snapshot.status
        except FeedbackError as error: return error.status
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda args: choose(*args), [(first,"keep_rule"), (second,"local_exception")]))
    assert sorted(results) == ["blocked_conflict", "ready"]
    assert len(first.load(v1.task_id, v1.version_id).decision_ids) == 1


def test_api_binds_choice_and_exposes_immutable_snapshot(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    token, origin = "rules-test-session-token-1234567890", "http://127.0.0.1:57843"
    client = TestClient(create_local_api(store=versions, snapshots=RuleSnapshotStore(versions), indexer=None, editor=None,
        renderer_factory=lambda _: None, session_token=token, allowed_origin=origin, font_fingerprint="test",
        selection_indexes=indexes, feedback_basis_loader=lambda c: basis_for(c, [academic_rule()])), base_url=origin)
    headers = {"X-AutoFormat-Session": token, "Origin": origin}
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    path = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}/feedback/{receipt.feedback_id}/rules"
    assert client.get(path).status_code == 401
    from autoformat.feedback_rules_contracts import FeedbackRulesReviewV2
    review = FeedbackRulesReviewV2.model_validate_json(client.get(path, headers=headers).text)
    answer = decision_for(review, context, "local_exception")
    wrong = answer.model_dump(mode="json"); wrong["expected_snapshot_id"] = "0"*64
    assert client.post(path+"/decide", headers=headers, json=wrong).status_code == 409
    response = client.post(path+"/decide", headers=headers, json=answer.model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["snapshot"]["status"] == "ready"
    snap = response.json()["snapshot"]
    assert client.get(f"/api/tasks/{v1.task_id}/versions/{v1.version_id}/feedback-rules/{snap['snapshot_id']}", headers=headers).json() == snap


def test_concurrent_identical_choice_is_an_exact_retry(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    stores = [rules_store(FeedbackStore(VersionStore(versions.root)), indexes, [academic_rule()]) for _ in range(2)]
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    review = stores[0].review(v1.task_id, v1.version_id, receipt.feedback_id)
    answer = decision_for(review, context, "local_exception")
    barrier = Barrier(2)
    for store in stores:
        original = store._append
        def race(*a, append=original, **k): barrier.wait(timeout=30); return append(*a, **k)
        store._append = race
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda s: s.decide(v1.task_id, v1.version_id, receipt.feedback_id, answer), stores))
    assert results[0] == results[1] and len(results[0].snapshot.decision_ids) == 1


def test_published_feedback_reference_is_atomic_and_inherited_targets_are_revalidated(feedback_env, indexes, tmp_path):
    from autoformat.version_store import VersionStoreError
    versions, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    pending = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    with pytest.raises(VersionStoreError):
        publish_fixture(versions, v1, tmp_path / "pending-publication", feedback_snapshot_id=pending.snapshot.snapshot_id)
    ready = store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(pending, context, "local_exception"))
    with pytest.raises(VersionStoreError):
        publish_fixture(versions, v1, tmp_path / "stale-publication", feedback_snapshot_id=pending.snapshot.snapshot_id)
    child = publish_fixture(versions, v1, tmp_path / "child", feedback_snapshot_id=ready.snapshot.snapshot_id)
    from dataclasses import asdict
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/version-node/version-node-1.1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(asdict(child))
    assert feedback.context(child.task_id, child.version_id).feedback_rules_snapshot_id == ready.snapshot.snapshot_id
    next_receipt, _, _ = saved(feedback, child, "取消斜体")
    rebased = store.review(child.task_id, child.version_id, next_receipt.feedback_id).snapshot
    assert rebased.parent_snapshot_id == ready.snapshot.snapshot_id and rebased.status == "ready"
    assert not any(f.status == "pending_target" for f in rebased.fragments)
    assert store.load(child.task_id, child.version_id) == rebased
    assert store.load(v1.task_id, v1.version_id, ready.snapshot.snapshot_id) == ready.snapshot


def test_decision_audit_payload_is_part_of_the_snapshot_hash(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    after = store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, "keep_rule"))
    with versions._transaction() as connection:
        row = connection.execute("SELECT * FROM feedback_rules_events WHERE kind='decision'").fetchone()
        payload = json.loads(row["payload_json"]); payload["raw_answer"] = "Forged audit answer"
        connection.execute("UPDATE feedback_rules_events SET payload_json=?,payload_sha256=? WHERE task_id=? AND sequence=?",
            (canonical_bytes(payload).decode(), content_hash(payload), row["task_id"], row["sequence"]))
    with pytest.raises(FeedbackError, match="重放"):
        store.load(v1.task_id, v1.version_id, after.snapshot.snapshot_id)


def test_character_partition_uses_utf16_and_preserves_script_disjointness():
    from autoformat.feedback_rule_compiler import _characters, _overlap, _subtract
    from autoformat.feedback_rules_contracts import FeedbackRuleSpan
    latin = _characters("paragraph", "A😀中1B", {"latin"})
    chinese = _characters("paragraph", "A😀中1B", {"chinese"})
    assert [(s.start_utf16,s.length_utf16) for s in latin] == [(0,1), (5,1)]
    assert [(s.start_utf16,s.length_utf16) for s in chinese] == [(3,1)]
    assert all(_overlap(a,b) is None for a in latin for b in chinese)
    full = FeedbackRuleSpan(object_id="paragraph", start_utf16=0, length_utf16=6)
    emoji = FeedbackRuleSpan(object_id="paragraph", start_utf16=1, length_utf16=2)
    assert [(s.start_utf16,s.length_utf16) for s in _subtract(full, emoji)] == [(0,1), (3,3)]


def test_global_update_rechecks_existing_local_exception(feedback_env, indexes):
    _, feedback, _, v1, _ = feedback_env
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    local = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    selected = store.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(local, context, "local_exception"))
    broad, _, _ = saved(feedback, v1, "全文字号16pt", requested_scope="document", selection=None)
    analysis = store.processor.get(v1.task_id, v1.version_id, broad.feedback_id)
    store.processor.confirm(v1.task_id, v1.version_id, broad.feedback_id, confirm_for(analysis, context,
        dict(action="confirm_scope", accepted_review_ids=[r.review_id for r in analysis.interpretation.scope_reviews])))
    review = store.review(v1.task_id, v1.version_id, broad.feedback_id)
    conflicts = [c for c in review.snapshot.conflicts if c.feedback_id == broad.feedback_id]
    assert len(conflicts) == 1
    assert next(r for r in review.snapshot.rules if r.rule_id == conflicts[0].existing_rule_id).feedback_id == receipt.feedback_id
    assert any(f.status == "pending_conflict" and f.value.normalized == 14 for f in review.snapshot.fragments)
    final = store.decide(v1.task_id, v1.version_id, broad.feedback_id, decision_for(review, context, "update_rule"))
    assert final.snapshot.status == "ready"
    assert all(f.value.normalized == 16 for f in final.snapshot.fragments if f.status == "verified")
    assert store.load(v1.task_id, v1.version_id, selected.snapshot.snapshot_id) == selected.snapshot


def test_default_basis_replays_saved_intake_without_a_model_service(tmp_path, indexes):
    import asyncio
    from docx import Document
    from brief_parser.bootstrap import build_service
    from brief_parser.config import Settings
    from autoformat.academic_intake import AcademicTaskIntake
    from autoformat.academic_decisions import AcademicDecisionStore
    from autoformat.feedback_rule_basis import source_loader
    versions = VersionStore(tmp_path / "store")
    paper = tmp_path / "original.docx"
    document = Document(); document.add_paragraph("Selectable preview text", style="Body Text"); document.save(paper)
    intake = AcademicTaskIntake(store=versions, service=build_service(Settings(environment="test", provider="fake", parser_isolation_mode="in_process")))
    result = asyncio.run(intake.create(request_id=new_id(), brief_filename="brief.txt", brief="正文：字号12pt。".encode(),
        paper_filename="paper.docx", paper=paper.read_bytes(), model_processing_acknowledged=True))
    baseline = AcademicDecisionStore(versions, intake).load(result.version.task_id)
    assert any(r.property_id == "font.size" and r.value.normalized == 12 for r in baseline.rules)
    v1 = publish_fixture(versions, result.version, tmp_path / "v1", rules_id=baseline.snapshot_id)
    feedback = FeedbackStore(versions)
    load = source_loader(versions, RuleSnapshotStore(versions))  # no intake/parser service supplied
    store = FeedbackRulesStore(FeedbackProcessor(feedback, indexes), basis_loader=load)
    receipt, _, _ = saved(feedback, v1, "字号14pt")
    review = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert review.snapshot.basis_available and len(review.snapshot.conflicts) == 1
    old = next(r for r in review.snapshot.rules if r.rule_id == review.snapshot.conflicts[0].existing_rule_id)
    assert old.source_kind == "academic" and old.value.normalized == 12 and old.evidence_quotes


def test_historical_snapshot_replays_before_a_later_target_choice(tmp_path, indexes):
    versions, feedback, v1 = custom_task(tmp_path, ["Selectable preview text", "Selectable preview text"])
    store = rules_store(feedback, indexes, [academic_rule()])
    receipt, context, _ = saved(feedback, v1, "字号14pt")
    before = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert before.parse_result.kind == "clarification_needed" and before.snapshot.pending_feedback_ids == [receipt.feedback_id]
    original = store.processor.selections.get(v1.task_id, v1.version_id, receipt.feedback_id)
    assert original.status == "ambiguous"
    store.processor.selections.confirm(v1.task_id, v1.version_id, receipt.feedback_id, answer_for(receipt, context, original))
    after = store.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert after.parse_result.kind == "new_rule" and len(after.snapshot.conflicts) == 1
    assert store.load(v1.task_id, v1.version_id, before.snapshot.snapshot_id) == before.snapshot
