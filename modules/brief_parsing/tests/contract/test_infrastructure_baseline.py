import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_declares_hardened_app_and_collector_resources() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]
    collector = compose["services"]["otel-collector"]

    assert app["read_only"] is True
    assert app["user"] == "10001:10001"
    assert app["cap_drop"] == ["ALL"]
    assert app["pids_limit"] == 128
    assert app["cpus"] == 2.0
    assert app["mem_limit"] == "4g"
    assert any(item.startswith("/tmp:") for item in app["tmpfs"])
    assert app["environment"]["BRIEF_PARSER_PARSER_ISOLATION_MODE"] == "process"
    assert app["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"].endswith(":4318")

    assert collector["read_only"] is True
    assert collector["cap_drop"] == ["ALL"]
    assert collector["pids_limit"] == 64
    assert collector["mem_limit"] == "512m"


def test_collector_accepts_otlp_and_exposes_prometheus_metrics() -> None:
    config = yaml.safe_load(
        (ROOT / "deploy" / "otel-collector-config.yaml").read_text(encoding="utf-8")
    )

    assert config["receivers"]["otlp"]["protocols"]["http"]["endpoint"].endswith(
        ":4318"
    )
    assert config["exporters"]["prometheus"]["endpoint"].endswith(":9464")
    assert config["service"]["pipelines"]["traces"]["exporters"] == ["debug"]
    assert config["service"]["pipelines"]["metrics"]["exporters"] == [
        "debug",
        "prometheus",
    ]


def test_runtime_image_is_non_root_and_defaults_to_process_isolation() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "3.12.14-slim-bookworm@sha256:" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "BRIEF_PARSER_PARSER_ISOLATION_MODE=process" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'ENTRYPOINT ["brief-parser"]' in dockerfile


def test_ci_actions_are_commit_pinned_and_smoke_tests_read_only_root() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    action_references = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)

    assert action_references
    assert all(
        re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference)
        for reference in action_references
    )
    assert "--read-only" in workflow
    assert "--memory 4g" in workflow
    assert "--cpus 2" in workflow
    assert "rootfs-must-remain-read-only" in workflow
