import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from brief_parser.api.app import create_app
from brief_parser.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="standalone",
        environment="test",
        provider="fake",
        storage_dir=tmp_path / "var",
        sqlite_path=tmp_path / "var" / "jobs.sqlite3",
        job_timeout_seconds=10,
        retention_days=1,
    )


def _submit(
    client: TestClient,
    *,
    content: bytes = "成片时长不得超过60秒。".encode(),
    idempotency_key: str = "idem-api-1",
):
    return client.post(
        "/v1/parse-jobs",
        data={
            "request": json.dumps(
                {
                    "domain": "advertising_brief",
                    "task_types": ["write_ad_script"],
                    "locale": "zh-CN",
                }
            )
        },
        files={"sources": ("brief.txt", content, "text/plain")},
        headers={"Idempotency-Key": idempotency_key},
    )


def _wait_for_terminal(client: TestClient, status_url: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(status_url)
        payload = response.json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_standalone_api_runs_job_and_returns_host_neutral_bundle(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ready"}

        created = _submit(client)
        assert created.status_code == 202
        links = created.json()
        status = _wait_for_terminal(client, links["status_url"])
        assert status == {
            "job_id": links["job_id"],
            "status": "completed",
            "readiness": "incomplete",
            "error": None,
        }

        result = client.get(links["result_url"])
        assert result.status_code == 200
        assert result.json()["bundle_version"] == "parse-bundle/1.0"
        assert result.json()["execution_briefs"]["write_ad_script"]["task_type"] == (
            "write_ad_script"
        )

        assert client.delete(links["status_url"]).status_code == 204
        assert client.get(links["status_url"]).status_code == 404


def test_standalone_api_enforces_idempotency_without_host_database(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        first = _submit(client)
        second = _submit(client)
        assert second.status_code == 202
        assert second.json()["job_id"] == first.json()["job_id"]

        conflict = _submit(client, content=b"different synthetic brief")
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_standalone_api_rejects_source_count_before_persistence(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(update={"max_sources": 2})
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/parse-jobs",
            data={
                "request": json.dumps(
                    {
                        "domain": "advertising_brief",
                        "task_types": ["write_ad_script"],
                        "locale": "zh-CN",
                    }
                )
            },
            files=[
                (
                    "sources",
                    (f"brief-{index}.txt", b"synthetic", "text/plain"),
                )
                for index in range(3)
            ],
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        assert response.json()["error"]["details"] == {"max_sources": 2}
        assert not any((settings.storage_dir / "uploads").iterdir())
        assert not any((settings.storage_dir / "artifacts").iterdir())
