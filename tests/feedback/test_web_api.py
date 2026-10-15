"""The public fixed shell must never expose protected task artifacts."""
from fastapi.testclient import TestClient

from autoformat.local_api import bind_local_api, create_local_api
from autoformat.rule_snapshots import RuleSnapshotStore

from conftest import publish_fixture

ORIGIN = "http://127.0.0.1:57843"
TOKEN = "web-test-local-session-token-with-32-characters"
HEADERS = {"X-AutoFormat-Session": TOKEN, "Origin": ORIGIN}


def web_client(store, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script type="module" src="/assets/main.js"></script>', encoding="utf-8")
    (dist / "assets/main.js").write_text("// fixed public bundle", encoding="utf-8")
    (dist / "assets/worker.mjs").write_text("// fixed module worker", encoding="utf-8")
    (dist / "assets/decoder.wasm").write_bytes(b"\0asm\x01\0\0\0")
    (dist / "private.txt").write_text("must not be served", encoding="utf-8")
    app = create_local_api(store=store, snapshots=RuleSnapshotStore(store), indexer=None, editor=None,
        renderer_factory=lambda _: None, session_token=TOKEN, allowed_origin=ORIGIN,
        font_fingerprint="test-fonts", web_dist_dir=dist)
    return TestClient(app, base_url=ORIGIN)


def test_public_shell_is_fixed_and_all_data_needs_session(feedback_env, tmp_path):
    store, _, _, v1, _ = feedback_env
    with web_client(store, tmp_path) as client:
        shell = client.get("/")
        assert shell.status_code == 200
        assert TOKEN not in shell.text and v1.task_id not in shell.text
        assert shell.headers["referrer-policy"] == "no-referrer"
        assert "script-src 'self'" in shell.headers["content-security-policy"]
        assert "connect-src 'self'" in shell.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in shell.headers["content-security-policy"]
        assert client.get("/assets/main.js").status_code == 200
        assert client.get("/assets/worker.mjs").headers["content-type"] == "application/javascript"
        assert client.get("/assets/decoder.wasm").headers["content-type"] == "application/wasm"
        for kind in ["docx", "preview", "report_json", "report_markdown"]:
            path = f"/api/tasks/{v1.task_id}/versions/{v1.version_id}/artifacts/{kind}"
            assert client.get(path).status_code == 401
            assert client.get(path, headers=HEADERS).status_code == 200
        assert client.get("/private.txt").status_code == 401
        assert client.get("/assets/../private.txt").status_code != 200
        assert client.get("/assets/%2e%2e/private.txt").status_code != 200
        assert client.get("/assets/%2e%2e/%2e%2e/versions.sqlite3").status_code != 200
        assert client.post("/", json={}).status_code == 401


def test_public_shell_still_checks_origin_and_host(feedback_env, tmp_path):
    store, _, _, _, _ = feedback_env
    with web_client(store, tmp_path) as client:
        for path in ["/", "/assets/main.js"]:
            assert client.get(path, headers={"Origin": "https://evil.test"}).status_code == 403
            assert client.get(path, headers={"Host": "evil.test"}).status_code == 403
        assert client.options("/", headers={"Origin": "https://evil.test"}).status_code == 403


def test_reading_historical_versions_keeps_working_parent(feedback_env, tmp_path):
    store, _, _, v1, _ = feedback_env
    v2 = publish_fixture(store, v1, tmp_path / "v2")
    before = {kind: store.artifact_path(v1.task_id, v1.version_id, kind).read_bytes()
              for kind in ["docx", "preview", "report_json", "report_markdown"]}
    with web_client(store, tmp_path) as client:
        path = f"/api/tasks/{v1.task_id}"
        listing = client.get(path + "/versions", headers=HEADERS).json()
        assert listing["working_version_id"] == v2.version_id
        assert len(listing["versions"]) == 3
        assert client.get(path + f"/versions/{v1.version_id}/feedback-context", headers=HEADERS).status_code == 200
        assert store.working_version_id(v1.task_id) == v2.version_id
        assert {kind: store.artifact_path(v1.task_id, v1.version_id, kind).read_bytes()
                for kind in before} == before
        assert client.get("/api/tasks/invalid/versions", headers=HEADERS).status_code == 422


def test_preview_only_host_cannot_call_edit_paths(feedback_env, tmp_path):
    store, _, _, v1, _ = feedback_env
    with web_client(store, tmp_path) as client:
        response = client.get(f"/api/tasks/{v1.task_id}/versions/{v1.version_id}/body-alignment/review", headers=HEADERS)
        assert response.status_code == 422 and response.json()["status"] == "unsupported_property"
        assert len(store.list_versions(v1.task_id)) == 2


def test_bound_host_launch_url_uses_fragment_and_never_repr_token(feedback_env):
    store, _, _, v1, _ = feedback_env
    host = bind_local_api(store=store, snapshots=RuleSnapshotStore(store), indexer=None, editor=None,
        renderer_factory=lambda _: None, font_fingerprint="test-fonts")
    try:
        assert host.url.startswith("http://127.0.0.1:")
        assert "?" not in host.ui_url(v1.task_id)
        assert host.ui_url(v1.task_id).endswith("&task=" + v1.task_id)
        assert host.session_token not in repr(host)
    finally:
        host.close()
