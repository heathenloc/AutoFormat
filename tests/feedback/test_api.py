"""HTTP intake exposes evidence only and preserves the local security boundary."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from autoformat.local_api import create_local_api
from autoformat.rule_snapshots import RuleSnapshotStore
from autoformat.version_store import new_id

from conftest import submission_for


ORIGIN = "http://127.0.0.1:57843"
TOKEN = "feedback-test-local-session-token-with-32-characters"
HEADERS = {"X-AutoFormat-Session": TOKEN, "Origin": ORIGIN}
ROOT = Path(__file__).resolve().parents[2]


class NoCall:
    def __getattr__(self, name):
        raise AssertionError("Feedback intake must not invoke an editor, renderer or indexer.")


def client_for(store):
    return TestClient(create_local_api(store=store, snapshots=RuleSnapshotStore(store),
        indexer=NoCall(), editor=NoCall(), renderer_factory=NoCall(),
        session_token=TOKEN, allowed_origin=ORIGIN, font_fingerprint="fixture-fonts"), base_url=ORIGIN)


def test_http_context_intake_replay_read_and_history(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    prefix = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}"
    with client_for(store) as client:
        response = client.get(prefix + "/feedback-context", headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        context = feedback.context(v1.task_id, v1.version_id)
        assert response.json() == context.model_dump(mode="json")
        request = submission_for(context).model_dump(mode="json")
        response = client.post(prefix + "/feedback", json=request, headers=HEADERS)
        assert response.status_code == 202
        receipt = response.json()
        assert receipt["status"] == "received"
        schema = json.loads((ROOT / "contracts/feedback-receipt/feedback-receipt-1.0.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(receipt)
        replay = client.post(prefix + "/feedback", json=request, headers=HEADERS)
        assert replay.status_code == 202 and replay.json()["replayed"]
        assert replay.json()["feedback_id"] == receipt["feedback_id"]
        record = client.get(prefix + "/feedback/" + receipt["feedback_id"], headers=HEADERS)
        assert record.status_code == 200
        assert record.json()["submission"] == request
        assert client.get(prefix + "/feedback", headers=HEADERS).json()["feedback"] == [receipt]
        assert len(store.list_versions(v1.task_id)) == 2


def test_http_input_cannot_forge_rules_anchors_or_server_paths(feedback_env):
    store, feedback, _, v1, _ = feedback_env
    prefix = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}"
    request = submission_for(feedback.context(v1.task_id, v1.version_id)).model_dump(mode="json")
    with client_for(store) as client:
        for field in ("status", "rules", "manifest", "anchor", "docx_path"):
            response = client.post(prefix + "/feedback", json={**request, field: "forged"}, headers=HEADERS)
            assert response.status_code == 422
            assert "forged" not in response.text
        no_version = {key: value for key, value in request.items() if key != "schema_version"}
        assert client.post(prefix + "/feedback", json=no_version, headers=HEADERS).status_code == 422
        changed = {**request, "expected_preview_pdf_sha256": "f" * 64}
        assert client.post(prefix + "/feedback", json=changed, headers=HEADERS).status_code == 409
        mismatched = {**request, "task_id": new_id()}
        assert client.post(prefix + "/feedback", json=mismatched, headers=HEADERS).status_code == 409
        assert feedback.list_receipts(v1.task_id, v1.version_id) == []


def test_feedback_routes_require_session_origin_and_loopback(feedback_env):
    store, feedback, v0, v1, _ = feedback_env
    prefix = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}"
    request = submission_for(feedback.context(v1.task_id, v1.version_id)).model_dump(mode="json")
    with client_for(store) as client:
        assert client.get(prefix + "/feedback-context").status_code == 401
        assert client.post(prefix + "/feedback", json=request).status_code == 401
        assert client.get(prefix + "/feedback", headers={**HEADERS, "Origin": "http://evil.test"}).status_code == 403
        assert client.get(prefix + "/feedback-context", headers={**HEADERS, "Host": "evil.test"}).status_code == 403
        old_prefix = f"/api/tasks/{v0.task_id}/versions/{v0.version_id}"
        assert client.get(old_prefix + "/feedback-context", headers=HEADERS).status_code == 422
        assert client.get(prefix + "/feedback/not-a-feedback-id", headers=HEADERS).status_code == 422
        assert client.get(f"/api/tasks/{v1.task_id}/versions/not-a-version/feedback-context", headers=HEADERS).status_code == 422
        # No confirmation/decision/snapshot write endpoint exists in this step.
        assert client.post(prefix + "/feedback/confirm", json={}, headers=HEADERS).status_code == 405
