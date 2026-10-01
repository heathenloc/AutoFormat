"""Dual-file intake publishes an honest V1 before any preview feedback."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pypdf import PdfReader

from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError, ErrorCode

from easyformat.academic_intake import AcademicTaskIntake
from easyformat.initial_draft import InitialDraftPublisher
from easyformat.local_api import create_local_api
from easyformat.preview import PreviewArtifact, PreviewError
from easyformat.rule_snapshots import RuleSnapshotStore
from easyformat.version_store import VersionStore, new_id


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:57843"
TOKEN = "academic-intake-session-token-long-enough"
BRIEF = "正文段落必须居中。".encode("utf-8")


def _pdf(path: Path) -> None:
    content = b"BT /F1 14 Tf 72 720 Td (Selectable preview text) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    startxref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend((f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
                   f"startxref\n{startxref}\n%%EOF\n").encode())
    path.write_bytes(output)


class FixtureRenderer:
    def __init__(self, root: Path) -> None:
        self.root = root

    def render(self, source_docx: Path, artifact_id: str) -> PreviewArtifact:
        relative = f"artifacts/previews/{artifact_id}.pdf"
        pdf = self.root / relative
        pdf.parent.mkdir(parents=True)
        _pdf(pdf)
        reader = PdfReader(pdf, strict=True)
        return PreviewArtifact(
            schema_version="preview-artifact/1.0", artifact_id=artifact_id,
            source_sha256=hashlib.sha256(source_docx.read_bytes()).hexdigest(),
            pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
            pdf_relative_path=relative, page_count=len(reader.pages),
            selectable_text_chars=sum(len(page.extract_text() or "") for page in reader.pages),
            renderer_id="fixture", renderer_version="1.0",
        )


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
        renderer_factory=FixtureRenderer, session_token=TOKEN,
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
                         "task-intake-1.1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    assert payload["replayed"] is False
    assert payload["phase"] == "initial_draft_ready"
    assert payload["initial_format_status"] == "unassessed"
    assert "未作格式修改" in payload["next_action"]
    assert payload["base_docx_sha256"] == hashlib.sha256(paper).hexdigest()
    assert [item.kind for item in store.list_versions(payload["task_id"])] == [
        "original", "output"]
    assert payload["initial_docx_sha256"] == payload["base_docx_sha256"]
    assert store.get_academic_intake(payload["task_id"]).brief_path.read_bytes() == BRIEF
    assert not (store.root / "rule_snapshots" / f"{payload['task_id']}.json").exists()

    headers = {"X-EasyFormat-Session": TOKEN, "Origin": ORIGIN}
    task = client.get(f"/api/tasks/{payload['task_id']}", headers=headers)
    assert task.status_code == 200
    assert task.json()["phase"] == payload["phase"]
    assert task.json()["working_version_id"] == payload["initial_version_id"]
    assert task.json()["initial_format_status"] == "unassessed"
    downloaded = client.get(
        f"/api/tasks/{payload['task_id']}/versions/{payload['initial_version_id']}/artifacts/docx",
        headers=headers)
    assert downloaded.status_code == 200 and downloaded.content == paper
    report = json.loads(store.artifact_path(
        payload["task_id"], payload["initial_version_id"], "report_json").read_text(encoding="utf-8"))
    assert report["summary"]["this_round_change_count"] == 0
    assert "未修改任何格式" in report["summary"]["note"]
    parsed = client.get(f"/api/tasks/{payload['task_id']}/academic-parse",
                        headers=headers)
    assert parsed.status_code == 200
    assert parsed.json()["bundle_version"] == "academic-parse-bundle/1.2"
    ruleset = parsed.json()["format_ruleset"]
    assert ruleset["rules"][0]["property_id"] == "paragraph.alignment"
    assert ruleset["rules"][0]["value"]["normalized"] == "center"
    assert parsed.json()["manifest"]["sources"][0]["sha256"] == hashlib.sha256(BRIEF).hexdigest()
    parse_schema = json.loads((ROOT / "contracts" / "academic-parse-bundle" /
                                   "academic-parse-bundle-1.2.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(parse_schema).validate(parsed.json())
    assert intake.load_bundle(payload["task_id"]).manifest.requested_task_types == [
        "format_academic_paper"]

    replay = _post(client, paper, request_id=request_id)
    assert replay.status_code == 200
    assert replay.json()["task_id"] == payload["task_id"]
    assert replay.json()["replayed"] is True
    assert replay.json()["initial_version_id"] == payload["initial_version_id"]
    assert len(store.list_versions(payload["task_id"])) == 2
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
    assert [item.kind for item in reopened.list_versions(payload["task_id"])] == [
        "original", "output"]
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
    assert store.get_version(task_id, response.json()["initial_version_id"]).status == "validation_failed"


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


def test_initial_preview_failure_keeps_v0_and_retry_publishes_v1(tmp_path: Path):
    class FailingRenderer:
        def render(self, source_docx, artifact_id):
            raise PreviewError("render_failed", "Synthetic preview failure.")

    store = VersionStore(tmp_path / "runtime")
    service = build_service(Settings(
        environment="test", provider="fake", parser_isolation_mode="in_process",
    ))
    intake = AcademicTaskIntake(store=store, service=service)
    result = asyncio.run(intake.create(
        request_id=new_id(), brief_filename="school.txt", brief=BRIEF,
        paper_filename="paper.docx", paper=_paper(tmp_path),
        model_processing_acknowledged=True,
    ))
    failing = InitialDraftPublisher(
        store=store, renderer_factory=lambda _: FailingRenderer(),
        font_fingerprint="test-fonts")
    with pytest.raises(PreviewError):
        failing.publish(result.version, result.bundle)
    assert [item.kind for item in store.list_versions(result.version.task_id)] == ["original"]
    assert store.working_version_id(result.version.task_id) == result.version.version_id

    working = InitialDraftPublisher(
        store=store, renderer_factory=FixtureRenderer, font_fingerprint="test-fonts")
    first = working.publish(result.version, result.bundle)
    assert first.kind == "output"
    assert working.publish(result.version, result.bundle).version_id == first.version_id
