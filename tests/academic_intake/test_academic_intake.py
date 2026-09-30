"""Dual-file local intake calls parse-only and leaves source classification open."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError, ErrorCode

from easyformat.academic_intake import AcademicTaskIntake
from easyformat.local_api import create_local_api
from easyformat.rule_snapshots import RuleSnapshotStore
from easyformat.version_store import VersionStore, new_id


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:57843"
TOKEN = "academic-intake-session-token-long-enough"
BRIEF = "正文段落必须居中。".encode("utf-8")


def _paper(tmp_path: Path) -> bytes:
    path = tmp_path / "paper.docx"
    document = Document()
    document.add_paragraph("Original thesis body.")
    document.save(path)
    return path.read_bytes()


@pytest.fixture
def setup(tmp_path: Path):
    store = VersionStore(tmp_path / "runtime")
    snapshots = RuleSnapshotStore(store)
    service = build_service(Settings(
        environment="test", provider="fake", parser_isolation_mode="in_process",
    ))
    intake = AcademicTaskIntake(store=store, service=service)
    app = create_local_api(
        store=store, snapshots=snapshots, indexer=None, editor=None,
        renderer_factory=lambda _: None, session_token=TOKEN,
        allowed_origin=ORIGIN, font_fingerprint="test-fonts", intake=intake,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, store, intake, _paper(tmp_path)


def _post(client: TestClient, paper: bytes, *, request_id: str, brief: bytes = BRIEF,
          acknowledged: str = "true"):
    return client.post(
        "/api/tasks", headers={"X-EasyFormat-Session": TOKEN, "Origin": ORIGIN},
        data={"request_id": request_id,
              "model_processing_acknowledged": acknowledged},
        files={
            "brief": ("school.txt", brief, "text/plain"),
            "paper": ("paper.docx", paper,
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        },
    )


def test_academic_intake_persists_parse_and_v0_without_executable_rules(setup):
    client, store, intake, paper = setup
    request_id = new_id()
    response = _post(client, paper, request_id=request_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    schema = json.loads((ROOT / "contracts" / "task-intake" /
                         "task-intake-1.0.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    assert payload["replayed"] is False
    assert payload["base_docx_sha256"] == hashlib.sha256(paper).hexdigest()
    assert store.list_versions(payload["task_id"])[0].kind == "original"
    assert store.get_academic_intake(payload["task_id"]).brief_path.read_bytes() == BRIEF
    assert not (store.root / "rule_snapshots" / f"{payload['task_id']}.json").exists()

    headers = {"X-EasyFormat-Session": TOKEN, "Origin": ORIGIN}
    task = client.get(f"/api/tasks/{payload['task_id']}", headers=headers)
    assert task.status_code == 200
    assert task.json()["phase"] == payload["phase"]
    parsed = client.get(f"/api/tasks/{payload['task_id']}/academic-parse",
                        headers=headers)
    assert parsed.status_code == 200
    assert parsed.json()["bundle_version"] == "academic-parse-bundle/1.0"
    assert parsed.json()["manifest"]["sources"][0]["sha256"] == hashlib.sha256(BRIEF).hexdigest()
    parse_schema = json.loads((ROOT / "contracts" / "academic-parse-bundle" /
                               "academic-parse-bundle-1.0.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(parse_schema).validate(parsed.json())
    assert intake.load_bundle(payload["task_id"]).manifest.requested_task_types == [
        "format_academic_paper"]

    replay = _post(client, paper, request_id=request_id)
    assert replay.status_code == 200
    assert replay.json()["task_id"] == payload["task_id"]
    assert replay.json()["replayed"] is True
    assert len(store.list_versions(payload["task_id"])) == 1
    reopened = VersionStore(store.root)
    replay_after_restart = asyncio.run(AcademicTaskIntake(
        store=reopened, service=object(),
    ).create(
        request_id=request_id, brief_filename="school.txt", brief=BRIEF,
        paper_filename="paper.docx", paper=paper,
        model_processing_acknowledged=True,
    ))
    assert replay_after_restart.replayed is True
    assert replay_after_restart.version.task_id == payload["task_id"]
    changed = _post(client, paper + b"x", request_id=request_id)
    assert changed.status_code == 409


def test_intake_rejects_unacknowledged_invalid_and_oversized_inputs(setup):
    client, store, _, paper = setup
    assert _post(client, paper, request_id=new_id(), acknowledged="false").status_code == 422
    assert _post(client, b"not-a-docx", request_id=new_id()).status_code == 422
    assert _post(client, paper, request_id=new_id(), brief=b"\x00bad").status_code == 422
    assert client.post("/api/tasks").status_code == 401
    with store._transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_intake_detects_stored_brief_tampering(setup):
    client, store, intake, paper = setup
    response = _post(client, paper, request_id=new_id())
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    record = store.get_academic_intake(task_id)
    record.brief_path.write_bytes(b"changed")
    headers = {"X-EasyFormat-Session": TOKEN, "Origin": ORIGIN}
    result = client.get(f"/api/tasks/{task_id}/academic-parse", headers=headers)
    assert result.status_code == 500
    assert client.get(f"/api/tasks/{task_id}", headers=headers).status_code == 500
    download = client.get(
        f"/api/tasks/{task_id}/versions/{response.json()['base_version_id']}/artifacts/docx",
        headers=headers)
    assert download.status_code == 500
    store.recover()
    assert store.get_version(task_id, response.json()["base_version_id"]).status == "validation_failed"


def test_parse_failure_does_not_create_v0(tmp_path: Path):
    class FailingParser:
        async def parse_academic_with_timeout(self, request, *, timeout_seconds):
            raise BriefParserError(ErrorCode.PROVIDER_TRANSIENT, "Temporary parse failure.")

    store = VersionStore(tmp_path / "runtime")
    intake = AcademicTaskIntake(store=store, service=FailingParser())
    with pytest.raises(BriefParserError):
        asyncio.run(intake.create(
            request_id=new_id(), brief_filename="school.txt", brief=BRIEF,
            paper_filename="paper.docx", paper=_paper(tmp_path),
            model_processing_acknowledged=True,
        ))
    with store._transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
