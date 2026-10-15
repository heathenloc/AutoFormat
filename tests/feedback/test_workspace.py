"""Version continuation, branch isolation and source-derived work item states."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from docx import Document
from fastapi.testclient import TestClient

from autoformat.feedback_execution import FeedbackExecutor
from autoformat.feedback_store import FeedbackError
from autoformat.feedback_work_queue import FeedbackWorkQueues
from autoformat.local_api import create_local_api
from autoformat.preview import PreviewError
from autoformat.rule_snapshots import RuleSnapshotStore
from autoformat.version_workspace import VersionWorkspace
from autoformat.version_store import new_id
from autoformat.workspace_contracts import VersionContinuationRequest, FeedbackWorkQueue
from test_execution import prepared, request_for, editor, FixtureRenderer
from test_processing import saved, confirm_for
from test_rules import rules_store, academic_rule, decision_for
from test_selection import indexes
from conftest import publish_fixture


def with_child(environment):
    versions, feedback, v0, v1, source = environment
    return versions, feedback, v0, v1, publish_fixture(versions, v1, source.parent / "extra-v2")


def continuation(version, current, **updates):
    data = dict(schema_version="version-continuation-request/1.0", request_id=new_id(),
        task_id=version.task_id, version_id=version.version_id,
        expected_docx_sha256=version.docx_sha256, expected_working_version_id=current)
    data.update(updates)
    return VersionContinuationRequest.model_validate(data)


def executor(store, renderer=FixtureRenderer):
    return FeedbackExecutor(store, editor=editor(), renderer_factory=renderer, font_fingerprint="test-fonts")


def test_continuation_is_durable_and_replay_does_not_rewind_a_later_origin(feedback_env):
    versions, feedback, v0, v1, v2 = with_child(feedback_env)
    rules = rules_store(feedback, None)
    workspace = VersionWorkspace(feedback, rules)
    before = {v.version_id: versions.artifact_path(v.task_id, v.version_id, "docx").read_bytes() for v in [v0, v1, v2]}
    request = continuation(v1, v2.version_id)
    result = workspace.continue_from(request)
    assert result.working_version_id == v1.version_id
    versions.select_working_version(v1.task_id, v2.version_id)
    replay = VersionWorkspace(feedback, rules).continue_from(request)
    assert replay.replayed and replay.continued_version_id == v1.version_id and replay.working_version_id == v2.version_id
    assert len(versions.list_versions(v1.task_id)) == 3
    assert before == {v.version_id: versions.artifact_path(v.task_id, v.version_id, "docx").read_bytes() for v in [v0, v1, v2]}
    with pytest.raises(FeedbackError): workspace.continue_from(request.model_copy(update={"expected_working_version_id": v1.version_id}))


def test_continuation_rejects_original_stale_pointer_and_changed_hash(feedback_env):
    versions, feedback, v0, v1, v2 = with_child(feedback_env)
    workspace = VersionWorkspace(feedback, rules_store(feedback, None))
    for request in [continuation(v0, v2.version_id), continuation(v1, v1.version_id), continuation(v1, v2.version_id, expected_docx_sha256="0"*64)]:
        with pytest.raises(FeedbackError): workspace.continue_from(request)
    assert versions.working_version_id(v1.task_id) == v2.version_id


def test_concurrent_continuations_use_compare_and_swap(feedback_env):
    versions, feedback, _, v1, v2 = with_child(feedback_env)
    request = continuation(v1, v2.version_id)
    workspaces = [VersionWorkspace(feedback, rules_store(feedback, None)) for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda workspace: workspace.continue_from(request), workspaces))
    assert results[0].continued_version_id == results[1].continued_version_id == v1.version_id
    assert sum(r.replayed for r in results) == 1


def test_returning_before_an_exception_creates_a_clean_branch(feedback_env, indexes):
    versions, feedback, v1, rules, context, receipt, review = prepared(feedback_env, indexes, rules=[academic_rule()])
    review = rules.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, "local_exception"))
    run = executor(rules)
    result = run.execute(request_for(review.snapshot, context))
    v2 = versions.get_version(v1.task_id, result.version_id)
    historical = {kind: versions.artifact_path(v1.task_id, v2.version_id, kind).read_bytes() for kind in ["docx", "report_json", "preview"]}
    VersionWorkspace(feedback, rules).continue_from(continuation(v1, v2.version_id))
    reset = rules.load(v1.task_id, v1.version_id)
    assert reset.inputs == [] and not reset.decision_ids
    assert rules.load(v1.task_id, v1.version_id, review.snapshot.snapshot_id) == review.snapshot
    next_receipt, next_context, _ = saved(feedback, v1, "加粗")
    next_review = rules.review(v1.task_id, v1.version_id, next_receipt.feedback_id)
    assert {i.interpretation.feedback_id for i in next_review.snapshot.inputs} == {next_receipt.feedback_id}
    child = run.execute(request_for(next_review.snapshot, next_context))
    branch = versions.get_version(v1.task_id, child.version_id)
    assert branch.parent_version_id == v1.version_id and branch.sequence == 3
    paragraph = Document(versions.artifact_path(v1.task_id, child.version_id, "docx")).paragraphs[0]
    assert all(r.font.size.pt == 12 for r in paragraph.runs)
    assert all(r.bold for r in paragraph.runs)
    assert historical == {kind: versions.artifact_path(v1.task_id, v2.version_id, kind).read_bytes() for kind in historical}
    restarted = rules_store(feedback, indexes, [academic_rule()])
    assert restarted.load(v1.task_id, v1.version_id) == next_review.snapshot


def test_continue_current_origin_preserves_pending_feedback(feedback_env, indexes):
    _, feedback, v1, rules, _, _, review = prepared(feedback_env, indexes)
    VersionWorkspace(feedback, rules).continue_from(continuation(v1, v1.version_id))
    assert rules.load(v1.task_id, v1.version_id) == review.snapshot


def test_continuation_rolls_back_when_the_rule_head_changes(feedback_env, indexes, monkeypatch):
    versions, feedback, v1, rules, _, _, review = prepared(feedback_env, indexes)
    v2 = publish_fixture(versions, v1, feedback_env[-1].parent / "race-v2")
    workspace = VersionWorkspace(feedback, rules)
    prepare = rules.prepare_restart
    def concurrent_review(task_id, version_id):
        staged = prepare(task_id, version_id)
        versions.select_working_version(task_id, version_id)
        receipt, _, _ = saved(feedback, v1, "加粗")
        rules.review(task_id, version_id, receipt.feedback_id)
        versions.select_working_version(task_id, v2.version_id)
        return staged
    monkeypatch.setattr(rules, "prepare_restart", concurrent_review)
    request = continuation(v1, v2.version_id)
    with pytest.raises(FeedbackError, match="规则核对头发生变化"):
        workspace.continue_from(request)
    assert versions.working_version_id(v1.task_id) == v2.version_id
    with versions._transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM version_continuations").fetchone()[0] == 0
    assert rules.load(v1.task_id, v1.version_id, review.snapshot.snapshot_id) == review.snapshot


def test_restart_rejects_a_corrupted_continuation_receipt(feedback_env, indexes):
    versions, feedback, v1, rules, _, _, _ = prepared(feedback_env, indexes)
    v2 = publish_fixture(versions, v1, feedback_env[-1].parent / "receipt-v2")
    workspace = VersionWorkspace(feedback, rules)
    request = continuation(v1, v2.version_id)
    workspace.continue_from(request)
    with versions._transaction() as connection:
        connection.execute("UPDATE version_continuations SET result_sha256=?", ("0"*64,))
    with pytest.raises(FeedbackError): rules.load(v1.task_id, v1.version_id)
    with pytest.raises(FeedbackError): workspace.continue_from(request)


def test_work_queue_recovers_scope_confirmation_and_completed_output(feedback_env, indexes):
    versions, feedback, _, v1, _ = feedback_env
    rules = rules_store(feedback, indexes)
    run = executor(rules)
    queues = FeedbackWorkQueues(rules, run)
    receipt, context, _ = saved(feedback, v1, "这一段居中")
    first = queues.get(v1.task_id, v1.version_id)
    assert first.items[0].status == "needs_scope" and first.items[0].raw_text == "这一段居中"
    assert rules._head(v1.task_id, v1.version_id) is None
    analysis = rules.processor.get(v1.task_id, v1.version_id, receipt.feedback_id)
    rules.processor.confirm(v1.task_id, v1.version_id, receipt.feedback_id, confirm_for(analysis, context,
        dict(action="confirm_scope", accepted_review_ids=[r.review_id for r in analysis.interpretation.scope_reviews])))
    review = rules.review(v1.task_id, v1.version_id, receipt.feedback_id)
    assert queues.get(v1.task_id, v1.version_id).items[0].status == "ready"
    result = run.execute(request_for(review.snapshot, context))
    restored = FeedbackWorkQueues(rules_store(feedback, indexes), executor(rules_store(feedback, indexes))).get(v1.task_id, v1.version_id)
    assert restored.items[0].status == "completed" and restored.items[0].output_version_id == result.version_id
    assert FeedbackWorkQueue.model_validate_json(restored.model_dump_json()) == restored
    assert len(versions.list_versions(v1.task_id)) == 3


def test_work_queue_distinguishes_keep_rule_consultation_and_no_change(feedback_env, indexes):
    _, feedback, v1, rules, context, receipt, review = prepared(feedback_env, indexes, rules=[academic_rule()])
    run = executor(rules)
    queues = FeedbackWorkQueues(rules, run)
    assert queues.get(v1.task_id, v1.version_id).items[0].status == "needs_conflict"
    rules.decide(v1.task_id, v1.version_id, receipt.feedback_id, decision_for(review, context, "keep_rule"))
    assert queues.get(v1.task_id, v1.version_id).items[0].status == "rule_kept"
    saved(feedback, v1, "为什么是宋体？")
    saved(feedback, v1, "润色正文")
    assert [item.status for item in queues.get(v1.task_id, v1.version_id).items[:2]] == ["out_of_scope", "question"]


@pytest.mark.parametrize("no_change", [False, True])
def test_work_queue_recovers_failed_retry_and_already_satisfied_receipts(feedback_env, indexes, no_change):
    versions, feedback, v1, rules, context, _, review = prepared(feedback_env, indexes, "取消加粗" if no_change else "字号14pt")
    class BrokenRenderer:
        def __init__(self, root): pass
        def render(self, source, artifact_id): raise PreviewError("render_failed", "renderer unavailable")
    run = executor(rules, BrokenRenderer)
    request = request_for(review.snapshot, context)
    if no_change: assert run.execute(request).phase == "no_document_change"
    else:
        with pytest.raises(PreviewError): run.execute(request)
    restarted_rules = rules_store(feedback, indexes)
    restarted = executor(restarted_rules)
    queue = FeedbackWorkQueues(restarted_rules, restarted).get(v1.task_id, v1.version_id)
    assert queue.items[0].status == ("no_document_change" if no_change else "failed")
    assert queue.items[0].execution_request_id == request.request_id
    assert len(versions.list_versions(v1.task_id)) == 2
    if not no_change:
        result = restarted.execute(request)
        queue = FeedbackWorkQueues(restarted_rules, restarted).get(v1.task_id, v1.version_id)
        assert queue.items[0].status == "completed" and queue.items[0].output_version_id == result.version_id


def test_queue_pagination_is_stable_when_new_feedback_is_appended(feedback_env):
    _, feedback, _, v1, _ = feedback_env
    rules = rules_store(feedback, None)
    queues = FeedbackWorkQueues(rules, FeedbackExecutor(rules, editor=None, renderer_factory=None, font_fingerprint="test"))
    for i in range(52): saved(feedback, v1, f"为什么是宋体？{i}")
    first = queues.get(v1.task_id, v1.version_id)
    assert len(first.items) == 50 and first.next_before is not None
    saved(feedback, v1, "为什么是宋体？新反馈")
    second = queues.get(v1.task_id, v1.version_id, before=first.next_before)
    assert len(second.items) == 2 and second.next_before is None
    assert not {i.feedback_id for i in first.items} & {i.feedback_id for i in second.items}


def test_workspace_routes_require_session_and_bind_path(feedback_env):
    versions, _, _, v1, v2 = with_child(feedback_env)
    token, origin = "workspace-test-session-token-1234567890", "http://127.0.0.1:57843"
    client = TestClient(create_local_api(store=versions, snapshots=RuleSnapshotStore(versions),
        indexer=None, editor=None, renderer_factory=None, session_token=token, allowed_origin=origin,
        font_fingerprint="test-fonts"), base_url=origin)
    path = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}"
    request = continuation(v1, v2.version_id).model_dump(mode="json")
    headers = {"X-AutoFormat-Session": token, "Origin": origin}
    assert client.post(path + "/continue", json=request).status_code == 401
    assert client.post(path + "/continue", json={**request, "version_id": v2.version_id}, headers=headers).status_code == 409
    assert client.post(path + "/continue", json={**request, "rules": []}, headers=headers).status_code == 422
    assert client.post(path + "/continue", json=request, headers=headers).json()["working_version_id"] == v1.version_id
    response = client.get(path + "/work-items", headers=headers)
    assert response.status_code == 200 and response.json()["items"] == []
    assert client.get(path + "/work-items?before=0", headers=headers).status_code == 422
