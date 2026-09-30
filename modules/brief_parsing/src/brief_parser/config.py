"""Validated environment configuration without framework coupling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from brief_parser.domain.base import StrictModel

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_SOURCES = 10
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_EXTRACTED_CHARS = 250_000
DEFAULT_JOB_TIMEOUT_SECONDS = 300
DEFAULT_RETENTION_DAYS = 30
DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS = 90
DEFAULT_PROVIDER_MAX_RETRIES = 2
DEFAULT_STRUCTURED_OUTPUT_MAX_RETRIES = 1
DEFAULT_PROVIDER_MAX_CONCURRENCY = 4
DEFAULT_JOB_TOKEN_BUDGET = 100_000
DEFAULT_PARSER_TIMEOUT_SECONDS = 60
DEFAULT_PARSER_CPU_TIME_SECONDS = 60
DEFAULT_PARSER_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
DEFAULT_PARSER_FILE_SIZE_LIMIT_BYTES = 256 * 1024 * 1024
DEFAULT_PARSER_OPEN_FILES_LIMIT = 128
DEFAULT_OTEL_METRIC_EXPORT_INTERVAL_MS = 60_000
DEFAULT_QWEN_MODEL_ID = "qwen3.7-flash-2026-07-15"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _optional(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _int(value: str | None, *, default: int) -> int:
    return default if value is None or not value.strip() else int(value)


class Settings(StrictModel):
    mode: Literal["standalone", "integrated"] = "standalone"
    environment: Literal["development", "test", "production"] = "development"
    storage_dir: Path = Path("var")
    sqlite_path: Path = Path("var/brief-parser.sqlite3")
    provider: Literal["openai", "qwen", "fake"] = "fake"
    extractor_model: str = "gpt-5.6-terra"
    auditor_model: str = "gpt-5.6-luna"
    resolver_model: str = "gpt-5.6-sol"
    extractor_reasoning: Literal["none", "minimal", "low", "medium", "high"] = "low"
    auditor_reasoning: Literal["none", "minimal", "low", "medium", "high"] = "low"
    resolver_reasoning: Literal["none", "minimal", "low", "medium", "high"] = "medium"
    provider_connect_timeout_seconds: int = Field(
        default=DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS,
        gt=0,
    )
    provider_read_timeout_seconds: int = Field(
        default=DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS,
        gt=0,
    )
    provider_max_retries: int = Field(default=DEFAULT_PROVIDER_MAX_RETRIES, ge=0, le=5)
    structured_output_max_retries: int = Field(
        default=DEFAULT_STRUCTURED_OUTPUT_MAX_RETRIES,
        ge=0,
        le=2,
    )
    provider_max_concurrency: int = Field(
        default=DEFAULT_PROVIDER_MAX_CONCURRENCY,
        gt=0,
        le=32,
    )
    job_token_budget: int = Field(default=DEFAULT_JOB_TOKEN_BUDGET, gt=0)
    max_file_bytes: int = Field(default=DEFAULT_MAX_FILE_BYTES, gt=0)
    max_sources: int = Field(default=DEFAULT_MAX_SOURCES, gt=0, le=10)
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, gt=0, le=100)
    max_extracted_chars: int = Field(default=DEFAULT_MAX_EXTRACTED_CHARS, gt=0)
    job_timeout_seconds: int = Field(default=DEFAULT_JOB_TIMEOUT_SECONDS, gt=0)
    parser_isolation_mode: Literal["auto", "process", "in_process"] = "auto"
    parser_timeout_seconds: int = Field(default=DEFAULT_PARSER_TIMEOUT_SECONDS, gt=0)
    parser_cpu_time_seconds: int = Field(
        default=DEFAULT_PARSER_CPU_TIME_SECONDS,
        gt=0,
    )
    parser_memory_limit_bytes: int = Field(
        default=DEFAULT_PARSER_MEMORY_LIMIT_BYTES,
        gt=0,
    )
    parser_file_size_limit_bytes: int = Field(
        default=DEFAULT_PARSER_FILE_SIZE_LIMIT_BYTES,
        gt=0,
    )
    parser_open_files_limit: int = Field(
        default=DEFAULT_PARSER_OPEN_FILES_LIMIT,
        ge=32,
    )
    otel_endpoint: str | None = None
    otel_service_name: str = "brief-parser"
    otel_metric_export_interval_ms: int = Field(
        default=DEFAULT_OTEL_METRIC_EXPORT_INTERVAL_MS,
        ge=1_000,
    )
    log_content: bool = False
    retention_days: int = Field(default=DEFAULT_RETENTION_DAYS, ge=1)
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    qwen_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    qwen_base_url: str = Field(default=DEFAULT_QWEN_BASE_URL, exclude=True, repr=False)
    qwen_enable_thinking: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        provider = _optional(env.get("BRIEF_PARSER_PROVIDER")) or "fake"
        extractor_default = (
            DEFAULT_QWEN_MODEL_ID if provider == "qwen" else "gpt-5.6-terra"
        )
        auditor_default = (
            DEFAULT_QWEN_MODEL_ID if provider == "qwen" else "gpt-5.6-luna"
        )
        resolver_default = (
            DEFAULT_QWEN_MODEL_ID if provider == "qwen" else "gpt-5.6-sol"
        )
        return cls(
            mode=_optional(env.get("BRIEF_PARSER_MODE")) or "standalone",
            environment=_optional(env.get("BRIEF_PARSER_ENV")) or "development",
            storage_dir=Path(_optional(env.get("BRIEF_PARSER_STORAGE_DIR")) or "var"),
            sqlite_path=Path(
                _optional(env.get("BRIEF_PARSER_SQLITE_PATH")) or "var/brief-parser.sqlite3"
            ),
            provider=provider,
            extractor_model=(
                _optional(env.get("BRIEF_PARSER_EXTRACTOR_MODEL")) or extractor_default
            ),
            auditor_model=(
                _optional(env.get("BRIEF_PARSER_AUDITOR_MODEL")) or auditor_default
            ),
            resolver_model=(
                _optional(env.get("BRIEF_PARSER_RESOLVER_MODEL")) or resolver_default
            ),
            extractor_reasoning=(
                _optional(env.get("BRIEF_PARSER_EXTRACTOR_REASONING")) or "low"
            ),
            auditor_reasoning=(
                _optional(env.get("BRIEF_PARSER_AUDITOR_REASONING")) or "low"
            ),
            resolver_reasoning=(
                _optional(env.get("BRIEF_PARSER_RESOLVER_REASONING")) or "medium"
            ),
            provider_connect_timeout_seconds=_int(
                env.get("BRIEF_PARSER_PROVIDER_CONNECT_TIMEOUT_SECONDS"),
                default=DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS,
            ),
            provider_read_timeout_seconds=_int(
                env.get("BRIEF_PARSER_PROVIDER_READ_TIMEOUT_SECONDS"),
                default=DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS,
            ),
            provider_max_retries=_int(
                env.get("BRIEF_PARSER_PROVIDER_MAX_RETRIES"),
                default=DEFAULT_PROVIDER_MAX_RETRIES,
            ),
            structured_output_max_retries=_int(
                env.get("BRIEF_PARSER_STRUCTURED_OUTPUT_MAX_RETRIES"),
                default=DEFAULT_STRUCTURED_OUTPUT_MAX_RETRIES,
            ),
            provider_max_concurrency=_int(
                env.get("BRIEF_PARSER_PROVIDER_MAX_CONCURRENCY"),
                default=DEFAULT_PROVIDER_MAX_CONCURRENCY,
            ),
            job_token_budget=_int(
                env.get("BRIEF_PARSER_JOB_TOKEN_BUDGET"),
                default=DEFAULT_JOB_TOKEN_BUDGET,
            ),
            max_file_bytes=_int(
                env.get("BRIEF_PARSER_MAX_FILE_BYTES"), default=DEFAULT_MAX_FILE_BYTES
            ),
            max_sources=_int(
                env.get("BRIEF_PARSER_MAX_SOURCES"), default=DEFAULT_MAX_SOURCES
            ),
            max_pages=_int(env.get("BRIEF_PARSER_MAX_PAGES"), default=DEFAULT_MAX_PAGES),
            max_extracted_chars=_int(
                env.get("BRIEF_PARSER_MAX_EXTRACTED_CHARS"),
                default=DEFAULT_MAX_EXTRACTED_CHARS,
            ),
            job_timeout_seconds=_int(
                env.get("BRIEF_PARSER_JOB_TIMEOUT_SECONDS"),
                default=DEFAULT_JOB_TIMEOUT_SECONDS,
            ),
            parser_isolation_mode=(
                _optional(env.get("BRIEF_PARSER_PARSER_ISOLATION_MODE")) or "auto"
            ),
            parser_timeout_seconds=_int(
                env.get("BRIEF_PARSER_PARSER_TIMEOUT_SECONDS"),
                default=DEFAULT_PARSER_TIMEOUT_SECONDS,
            ),
            parser_cpu_time_seconds=_int(
                env.get("BRIEF_PARSER_PARSER_CPU_TIME_SECONDS"),
                default=DEFAULT_PARSER_CPU_TIME_SECONDS,
            ),
            parser_memory_limit_bytes=_int(
                env.get("BRIEF_PARSER_PARSER_MEMORY_LIMIT_BYTES"),
                default=DEFAULT_PARSER_MEMORY_LIMIT_BYTES,
            ),
            parser_file_size_limit_bytes=_int(
                env.get("BRIEF_PARSER_PARSER_FILE_SIZE_LIMIT_BYTES"),
                default=DEFAULT_PARSER_FILE_SIZE_LIMIT_BYTES,
            ),
            parser_open_files_limit=_int(
                env.get("BRIEF_PARSER_PARSER_OPEN_FILES_LIMIT"),
                default=DEFAULT_PARSER_OPEN_FILES_LIMIT,
            ),
            otel_endpoint=_optional(env.get("OTEL_EXPORTER_OTLP_ENDPOINT")),
            otel_service_name=(
                _optional(env.get("OTEL_SERVICE_NAME")) or "brief-parser"
            ),
            otel_metric_export_interval_ms=_int(
                env.get("OTEL_METRIC_EXPORT_INTERVAL"),
                default=DEFAULT_OTEL_METRIC_EXPORT_INTERVAL_MS,
            ),
            log_content=_bool(env.get("BRIEF_PARSER_LOG_CONTENT"), default=False),
            retention_days=_int(
                env.get("BRIEF_PARSER_RETENTION_DAYS"), default=DEFAULT_RETENTION_DAYS
            ),
            openai_api_key=_optional(env.get("OPENAI_API_KEY")),
            qwen_api_key=_optional(env.get("DASHSCOPE_API_KEY")),
            qwen_base_url=(
                _optional(env.get("DASHSCOPE_BASE_URL")) or DEFAULT_QWEN_BASE_URL
            ),
            qwen_enable_thinking=_bool(
                env.get("BRIEF_PARSER_QWEN_ENABLE_THINKING"),
                default=False,
            ),
        )

    @model_validator(mode="after")
    def validate_security_policy(self) -> Self:
        if self.environment == "production" and self.provider == "fake":
            raise ValueError("fake provider is forbidden in production")
        if self.environment == "production" and self.log_content:
            raise ValueError("content logging is forbidden in production")
        if self.environment == "production" and self.parser_isolation_mode == "in_process":
            raise ValueError("in-process parser isolation is forbidden in production")
        if self.provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        if self.provider == "qwen" and self.qwen_api_key is None:
            raise ValueError("DASHSCOPE_API_KEY is required for the qwen provider")
        if self.provider == "qwen" and {
            self.extractor_model,
            self.auditor_model,
            self.resolver_model,
        } != {DEFAULT_QWEN_MODEL_ID}:
            raise ValueError(
                "qwen provider roles must use the fixed "
                f"{DEFAULT_QWEN_MODEL_ID} snapshot"
            )
        if self.otel_endpoint is not None and not self.otel_endpoint.startswith(
            ("http://", "https://")
        ):
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must use http or https")
        return self

    def manifest_summary(self) -> dict[str, str | int | bool]:
        """Return non-secret settings suitable for a parse manifest."""

        return {
            "mode": self.mode,
            "environment": self.environment,
            "provider": self.provider,
            "extractor_model": self.extractor_model,
            "auditor_model": self.auditor_model,
            "resolver_model": self.resolver_model,
            "extractor_reasoning": self.extractor_reasoning,
            "auditor_reasoning": self.auditor_reasoning,
            "resolver_reasoning": self.resolver_reasoning,
            "provider_connect_timeout_seconds": self.provider_connect_timeout_seconds,
            "provider_read_timeout_seconds": self.provider_read_timeout_seconds,
            "provider_max_retries": self.provider_max_retries,
            "structured_output_max_retries": self.structured_output_max_retries,
            "provider_max_concurrency": self.provider_max_concurrency,
            "job_token_budget": self.job_token_budget,
            "max_file_bytes": self.max_file_bytes,
            "max_sources": self.max_sources,
            "max_pages": self.max_pages,
            "max_extracted_chars": self.max_extracted_chars,
            "job_timeout_seconds": self.job_timeout_seconds,
            "parser_isolation_mode": self.parser_isolation_mode,
            "parser_timeout_seconds": self.parser_timeout_seconds,
            "parser_cpu_time_seconds": self.parser_cpu_time_seconds,
            "parser_memory_limit_bytes": self.parser_memory_limit_bytes,
            "parser_file_size_limit_bytes": self.parser_file_size_limit_bytes,
            "parser_open_files_limit": self.parser_open_files_limit,
            "otel_enabled": self.otel_endpoint is not None,
            "otel_service_name": self.otel_service_name,
            "otel_metric_export_interval_ms": self.otel_metric_export_interval_ms,
            "log_content": self.log_content,
            "retention_days": self.retention_days,
            "qwen_enable_thinking": self.qwen_enable_thinking,
        }
