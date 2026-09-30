import pytest
from pydantic import ValidationError

from brief_parser.adapters.qwen_provider import QWEN_FIXED_MODEL_ID
from brief_parser.config import Settings


def test_default_settings_are_safe_for_local_development() -> None:
    settings = Settings.from_env({})

    assert settings.provider == "fake"
    assert settings.mode == "standalone"
    assert settings.provider_connect_timeout_seconds == 10
    assert settings.provider_read_timeout_seconds == 90
    assert settings.provider_max_retries == 2
    assert settings.structured_output_max_retries == 1
    assert settings.provider_max_concurrency == 4
    assert settings.job_token_budget == 100_000
    assert settings.max_sources == 10
    assert settings.parser_isolation_mode == "auto"
    assert settings.parser_timeout_seconds == 60
    assert settings.parser_memory_limit_bytes == 1024 * 1024 * 1024
    assert settings.otel_endpoint is None
    assert "openai_api_key" not in settings.manifest_summary()


def test_provider_limits_are_configurable_from_environment() -> None:
    settings = Settings.from_env(
        {
            "BRIEF_PARSER_PROVIDER_MAX_CONCURRENCY": "3",
            "BRIEF_PARSER_JOB_TOKEN_BUDGET": "25000",
            "BRIEF_PARSER_MAX_SOURCES": "6",
            "BRIEF_PARSER_PARSER_ISOLATION_MODE": "in_process",
            "BRIEF_PARSER_PARSER_TIMEOUT_SECONDS": "45",
            "BRIEF_PARSER_PARSER_MEMORY_LIMIT_BYTES": "536870912",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "OTEL_SERVICE_NAME": "brief-parser-test",
        }
    )

    assert settings.provider_max_concurrency == 3
    assert settings.job_token_budget == 25_000
    assert settings.max_sources == 6
    assert settings.parser_isolation_mode == "in_process"
    assert settings.parser_timeout_seconds == 45
    assert settings.parser_memory_limit_bytes == 536_870_912
    assert settings.otel_endpoint == "http://collector:4318"
    assert settings.otel_service_name == "brief-parser-test"
    assert settings.manifest_summary()["provider_max_concurrency"] == 3
    assert settings.manifest_summary()["job_token_budget"] == 25_000
    assert settings.manifest_summary()["max_sources"] == 6


def test_openai_key_is_not_serialized() -> None:
    settings = Settings.from_env(
        {"BRIEF_PARSER_PROVIDER": "openai", "OPENAI_API_KEY": "synthetic-secret"}
    )

    assert "synthetic-secret" not in settings.model_dump_json()
    assert "synthetic-secret" not in repr(settings)


def test_qwen_provider_uses_fixed_snapshot_and_keeps_credentials_secret() -> None:
    settings = Settings.from_env(
        {
            "BRIEF_PARSER_PROVIDER": "qwen",
            "DASHSCOPE_API_KEY": "synthetic-qwen-secret",
        }
    )

    assert settings.extractor_model == QWEN_FIXED_MODEL_ID
    assert settings.auditor_model == QWEN_FIXED_MODEL_ID
    assert settings.resolver_model == QWEN_FIXED_MODEL_ID
    assert settings.qwen_enable_thinking is False
    assert "synthetic-qwen-secret" not in settings.model_dump_json()
    assert "synthetic-qwen-secret" not in repr(settings)
    assert "qwen_api_key" not in settings.manifest_summary()
    assert "qwen_base_url" not in settings.manifest_summary()


def test_qwen_thinking_mode_is_explicitly_configurable() -> None:
    settings = Settings.from_env(
        {
            "BRIEF_PARSER_PROVIDER": "qwen",
            "DASHSCOPE_API_KEY": "synthetic-qwen-secret",
            "BRIEF_PARSER_QWEN_ENABLE_THINKING": "true",
        }
    )

    assert settings.qwen_enable_thinking is True


def test_qwen_provider_rejects_model_override() -> None:
    with pytest.raises(
        ValidationError,
        match="qwen provider roles must use the fixed",
    ):
        Settings.from_env(
            {
                "BRIEF_PARSER_PROVIDER": "qwen",
                "DASHSCOPE_API_KEY": "synthetic-qwen-secret",
                "BRIEF_PARSER_EXTRACTOR_MODEL": "qwen3.7-flash",
            }
        )


def test_qwen_provider_requires_api_key() -> None:
    with pytest.raises(
        ValidationError,
        match="DASHSCOPE_API_KEY is required for the qwen provider",
    ):
        Settings.from_env({"BRIEF_PARSER_PROVIDER": "qwen"})


def test_fake_provider_is_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="fake provider is forbidden in production"):
        Settings.from_env(
            {"BRIEF_PARSER_ENV": "production", "BRIEF_PARSER_PROVIDER": "fake"}
        )


def test_content_logging_is_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="content logging is forbidden in production"):
        Settings.from_env(
            {
                "BRIEF_PARSER_ENV": "production",
                "BRIEF_PARSER_PROVIDER": "openai",
                "BRIEF_PARSER_LOG_CONTENT": "true",
                "OPENAI_API_KEY": "synthetic-secret",
            }
        )


def test_in_process_parser_is_forbidden_in_production() -> None:
    with pytest.raises(
        ValidationError,
        match="in-process parser isolation is forbidden in production",
    ):
        Settings.from_env(
            {
                "BRIEF_PARSER_ENV": "production",
                "BRIEF_PARSER_PROVIDER": "openai",
                "OPENAI_API_KEY": "synthetic-secret",
                "BRIEF_PARSER_PARSER_ISOLATION_MODE": "in_process",
            }
        )


def test_otel_endpoint_requires_http_transport() -> None:
    with pytest.raises(
        ValidationError,
        match="OTEL_EXPORTER_OTLP_ENDPOINT must use http or https",
    ):
        Settings.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "collector:4318"})
