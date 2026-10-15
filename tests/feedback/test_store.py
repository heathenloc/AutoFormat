"""Version/preview identity, immutable audit records, idempotency and isolation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from autoformat.feedback_contracts import FeedbackSubmission, content_hash
from autoformat.feedback_store import FeedbackError, FeedbackStore
from autoformat.version_store import VersionStore, VersionStoreError, new_id

from conftest import hash_file, publish_fixture, submission_for


def test_intake_preserves_raw_text_and_versions_across_restart(feedback_env):
    store, feedback, v0, v1, source = feedback_env
    context = feedback.context(v1.task_id, v1.version_id)
    artifacts = {kind: hash_file(store.artifact_path(v1.task_id, v1.version_id, kind))
                 for kind in ("docx", "preview", "report_json", "report_markdown")}
    request = submission_for(context)
    receipt = feedback.submit(v1.task_id, v1.version_id, request)
    assert receipt.status == "received" and receipt.next_action == "pending_feedback_processing"
    reopened = VersionStore(store.root)
    restored = FeedbackStore(reopened)
    record = restored.get(v1.task_id, v1.version_id, receipt.feedback_id)
    assert record.submission == request
    assert record.submission.raw_text == "  这一段改为居中\n"
    assert record.source_submission_sha256 == content_hash(request.model_dump(mode="json"))
    assert len(reopened.list_versions(v1.task_id)) == 2
    assert not reopened.list_decisions(v1.task_id)
    assert hash_file(source) == v0.docx_sha256
    assert restored.list_receipts(v1.task_id, v1.version_id)[0].feedback_id == receipt.feedback_id
    for kind, digest in artifacts.items():
        assert hash_file(reopened.artifact_path(v1.task_id, v1.version_id, kind)) == digest


def test_same_request_is_atomic_and_different_input_is_rejected(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(lambda _: feedback.submit(v1.task_id, v1.version_id, request), range(4)))
    assert len({item.feedback_id for item in receipts}) == 1
    assert sum(not item.replayed for item in receipts) == 1
    assert len(feedback.list_receipts(v1.task_id, v1.version_id)) == 1
    altered = request.model_copy(update={"raw_text": "不同要求"})
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, altered)
    assert error.value.status == "blocked_conflict"
    assert "不同要求" not in str(error.value)


@pytest.mark.parametrize("changes,status", [
    ({"expected_base_docx_sha256": "f" * 64}, "stale_base_version"),
    ({"expected_context_id": "f" * 64}, "stale_base_version"),
    ({"preview_artifact_id": "other-preview"}, "stale_preview"),
    ({"expected_preview_pdf_sha256": "f" * 64}, "stale_preview"),
])
def test_rejects_stale_identity_before_saving(feedback_env, changes, status):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id), **changes)
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, request)
    assert error.value.status == status
    assert feedback.list_receipts(v1.task_id, v1.version_id) == []


def test_feedback_is_only_available_after_v1_and_within_its_pages(feedback_env):
    _, feedback, v0, v1, _ = feedback_env
    with pytest.raises(FeedbackError) as error:
        feedback.context(v0.task_id, v0.version_id)
    assert error.value.status == "needs_user_input"
    request = submission_for(feedback.context(v1.task_id, v1.version_id)).model_dump(mode="json")
    request["selection"]["spans"][0]["page"] = 2
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, FeedbackSubmission.model_validate(request))
    assert error.value.status == "needs_user_input"


def test_history_keeps_its_rules_and_old_feedback_does_not_follow_task_head(feedback_env, tmp_path):
    store, feedback, _, v1, _ = feedback_env
    context1 = feedback.context(v1.task_id, v1.version_id)
    request = submission_for(context1)
    receipt = feedback.submit(v1.task_id, v1.version_id, request)
    v2 = publish_fixture(store, v1, tmp_path / "v2", rules_id="rules-v2")
    assert feedback.context(v2.task_id, v2.version_id).rules_snapshot_id == "rules-v2"
    assert feedback.context(v1.task_id, v1.version_id) == context1
    # Retrying an already accepted old request retrieves its original record.
    assert feedback.submit(v1.task_id, v1.version_id, request).replayed
    assert feedback.get(v1.task_id, v1.version_id, receipt.feedback_id).submission == request
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, submission_for(context1))
    assert error.value.status == "stale_base_version"
    store.select_working_version(v1.task_id, v1.version_id)
    assert not feedback.submit(v1.task_id, v1.version_id, submission_for(context1)).replayed
    assert feedback.context(v1.task_id, v1.version_id).rules_snapshot_id == "rules-v1"
    assert len(store.list_versions(v1.task_id)) == 3


def test_cross_task_or_version_feedback_is_not_visible(feedback_env, tmp_path):
    store, feedback, _, v1, source = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    receipt = feedback.submit(v1.task_id, v1.version_id, request)
    other0 = store.create_task(source)
    other1 = publish_fixture(store, other0, tmp_path / "other-v1")
    with pytest.raises(FeedbackError) as error:
        feedback.get(other1.task_id, other1.version_id, receipt.feedback_id)
    assert error.value.status == "needs_user_input"
    with pytest.raises(FeedbackError) as error:
        feedback.submit(other1.task_id, other1.version_id, request)
    assert error.value.status == "stale_base_version"


def test_working_version_change_between_context_read_and_insert_is_rejected(feedback_env, tmp_path, monkeypatch):
    store, feedback, _, v1, _ = feedback_env
    original_context = feedback.context
    request = submission_for(original_context(v1.task_id, v1.version_id))
    v2 = publish_fixture(store, v1, tmp_path / "v2-race", rules_id="rules-v2")
    store.select_working_version(v1.task_id, v1.version_id)
    def context_then_switch(task_id, version_id):
        context = original_context(task_id, version_id)
        store.select_working_version(task_id, v2.version_id)
        return context
    monkeypatch.setattr(feedback, "context", context_then_switch)
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, request)
    assert error.value.status == "stale_base_version"
    with store._transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM feedback_submissions").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["docx", "preview", "preview_metadata"])
def test_changed_artifact_blocks_feedback(feedback_env, kind):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    path = store.artifact_path(v1.task_id, v1.version_id, kind)
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(VersionStoreError) as error:
        feedback.submit(v1.task_id, v1.version_id, request)
    assert error.value.status == "validation_failed"


def test_record_tampering_and_internal_validation_bypass_are_rejected(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    with pytest.raises(FeedbackError) as error:
        feedback.submit(v1.task_id, v1.version_id, request.model_copy(update={"requested_scope": "arbitrary"}))
    assert error.value.status == "needs_user_input"
    receipt = feedback.submit(v1.task_id, v1.version_id, request)
    with store._transaction() as connection:
        connection.execute("UPDATE feedback_submissions SET request_id=? WHERE feedback_id=?", (new_id(), receipt.feedback_id))
    with pytest.raises(FeedbackError) as error:
        feedback.get(v1.task_id, v1.version_id, receipt.feedback_id)
    assert error.value.status == "validation_failed"


def test_feedback_payload_tampering_is_rejected(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    receipt = feedback.submit(v1.task_id, v1.version_id, request)
    with store._transaction() as connection:
        connection.execute("UPDATE feedback_submissions SET payload_json='{}' WHERE feedback_id=?", (receipt.feedback_id,))
    with pytest.raises(FeedbackError) as error:
        feedback.list_receipts(v1.task_id, v1.version_id)
    assert error.value.status == "validation_failed"


def test_request_shape_and_configured_size_limits(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    request = submission_for(feedback.context(v1.task_id, v1.version_id))
    payload = request.model_dump(mode="json")
    for field in ("rules", "docx_xml_path", "status", "anchor", "manifest"):
        with pytest.raises(ValidationError):
            FeedbackSubmission.model_validate({**payload, field: "untrusted"})
    with pytest.raises(ValidationError):
        FeedbackSubmission.model_validate({**payload, "selection": None})
    with pytest.raises(ValidationError):
        FeedbackSubmission.model_validate({**payload, "raw_text": " \n"})
    without_selection = FeedbackSubmission.model_validate({**payload, "selection": None, "requested_scope": "document"})
    assert without_selection.selection is None
    with pytest.raises(FeedbackError) as error:
        FeedbackStore(store, max_request_bytes=1).submit(v1.task_id, v1.version_id, request)
    assert error.value.status == "needs_user_input"
