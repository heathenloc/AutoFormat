"""Alibaba Cloud Model Studio Qwen adapter using OpenAI-compatible Chat APIs."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.model_provider import (
    ModelOutputT,
    ModelRequestContext,
    ProviderMessage,
    StructuredModelResult,
    TokenUsage,
)

QWEN_FIXED_MODEL_ID = "qwen3.7-flash-2026-07-15"
QWEN_BEIJING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_PUBLIC_HOSTS = frozenset(
    {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
        "cn-hongkong.dashscope.aliyuncs.com",
    }
)

Sleep = Callable[[float], Awaitable[None]]


class QwenModelRoute(StrictModel):
    model_id: Identifier = QWEN_FIXED_MODEL_ID
    enable_thinking: bool = False
    temperature: float = Field(default=0.0, ge=0, lt=2)
    max_completion_tokens: int = Field(default=8_000, gt=0)


class QwenProviderConfig(StrictModel):
    api_key: SecretStr = Field(exclude=True, repr=False)
    base_url: str = Field(
        default=QWEN_BEIJING_BASE_URL,
        exclude=True,
        repr=False,
    )
    routes: Mapping[ModelRole, QwenModelRoute]
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=90.0, gt=0)
    transient_max_retries: int = Field(default=2, ge=0, le=5)
    incomplete_max_retries: int = Field(default=1, ge=0, le=2)
    backoff_base_seconds: float = Field(default=0.25, ge=0)
    backoff_jitter_seconds: float = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def validate_provider_config(self) -> QwenProviderConfig:
        required = {ModelRole.EXTRACTOR, ModelRole.AUDITOR, ModelRole.RESOLVER}
        missing = required - set(self.routes)
        if missing:
            missing_names = sorted(item.value for item in missing)
            raise ValueError(f"missing Qwen model routes: {missing_names}")

        parsed = urlsplit(self.base_url)
        hostname = parsed.hostname or ""
        is_model_studio_host = (
            hostname in QWEN_PUBLIC_HOSTS or hostname.endswith(".maas.aliyuncs.com")
        )
        if (
            parsed.scheme != "https"
            or not is_model_studio_host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.rstrip("/").endswith("/compatible-mode/v1")
        ):
            raise ValueError(
                "Qwen base_url must be an HTTPS Alibaba Cloud Model Studio "
                "compatible-mode/v1 endpoint"
            )
        return self


class _ChatCompletionsAPI(Protocol):
    async def parse(self, **kwargs: Any) -> Any:
        """Call OpenAI-compatible Chat Completions structured parsing."""


class _ChatAPI(Protocol):
    @property
    def completions(self) -> _ChatCompletionsAPI:
        """Return the Chat Completions resource."""


class _QwenClient(Protocol):
    @property
    def chat(self) -> _ChatAPI:
        """Return the Chat resource."""


class QwenModelProvider:
    provider_alias = "qwen"

    def __init__(
        self,
        config: QwenProviderConfig,
        *,
        client: _QwenClient | None = None,
        sleep: Sleep = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._random_value = random_value
        configured_client: object = client
        if configured_client is None:
            timeout = httpx2.Timeout(
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.read_timeout_seconds,
                pool=config.connect_timeout_seconds,
            )
            configured_client = AsyncOpenAI(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout=timeout,
                max_retries=0,
            )
        self._client = cast(_QwenClient, configured_client)

    async def structured_generate(
        self,
        *,
        role: ModelRole,
        messages: Sequence[ProviderMessage],
        output_schema: type[ModelOutputT],
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ModelOutputT]:
        del request_context
        route = self._config.routes.get(role)
        if route is None:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "请求的模型角色没有配置 Provider route。",
                details={"role": role.value},
            )

        transient_retries = 0
        incomplete_retries = 0
        started_at = perf_counter()
        while True:
            try:
                response = await self._client.chat.completions.parse(
                    model=route.model_id,
                    messages=[
                        {"role": message.role, "content": message.content}
                        for message in messages
                    ],
                    response_format=output_schema,
                    temperature=route.temperature,
                    max_completion_tokens=route.max_completion_tokens,
                    extra_body={"enable_thinking": route.enable_thinking},
                )
            except LengthFinishReasonError:
                if incomplete_retries < self._config.incomplete_max_retries:
                    incomplete_retries += 1
                    await self._backoff(transient_retries + incomplete_retries)
                    continue
                return self._incomplete_result(
                    route=route,
                    started_at=started_at,
                    reason="max_completion_tokens",
                    retry_count=transient_retries + incomplete_retries,
                )
            except ContentFilterFinishReasonError:
                return StructuredModelResult[ModelOutputT](
                    output=None,
                    provider_alias=self.provider_alias,
                    model_id=route.model_id,
                    latency_ms=self._latency_ms(started_at),
                    completion_status="refused",
                    refusal_reason="content_filter",
                    retry_count=transient_retries + incomplete_retries,
                )
            except (
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                InternalServerError,
            ) as exc:
                if transient_retries >= self._config.transient_max_retries:
                    raise BriefParserError(
                        ErrorCode.PROVIDER_TRANSIENT,
                        "Qwen Provider 暂时不可用，请稍后重试。",
                        retryable=True,
                        details={"role": role.value, "retry_count": transient_retries},
                    ) from exc
                transient_retries += 1
                await self._backoff(transient_retries)
                continue
            except ValidationError:
                if incomplete_retries < self._config.incomplete_max_retries:
                    incomplete_retries += 1
                    await self._backoff(transient_retries + incomplete_retries)
                    continue
                return self._incomplete_result(
                    route=route,
                    started_at=started_at,
                    reason="schema_invalid",
                    retry_count=transient_retries + incomplete_retries,
                )
            except APIStatusError as exc:
                can_retry = transient_retries < self._config.transient_max_retries
                if exc.status_code >= 500 and can_retry:
                    transient_retries += 1
                    await self._backoff(transient_retries)
                    continue
                raise self._non_retryable(role) from exc
            except OpenAIError as exc:
                raise self._non_retryable(role) from exc

            retry_count = transient_retries + incomplete_retries
            choice = self._first_choice(response)
            refusal = self._refusal(choice)
            if refusal is not None:
                return StructuredModelResult[ModelOutputT](
                    output=None,
                    provider_alias=self.provider_alias,
                    model_id=route.model_id,
                    provider_request_id=self._response_id(response),
                    token_usage=self._token_usage(response),
                    latency_ms=self._latency_ms(started_at),
                    completion_status="refused",
                    refusal_reason=refusal,
                    retry_count=retry_count,
                )

            parsed = self._parsed(choice)
            try:
                output = None if parsed is None else output_schema.model_validate(parsed)
            except ValidationError:
                output = None
            if output is not None:
                return StructuredModelResult[ModelOutputT](
                    output=output,
                    provider_alias=self.provider_alias,
                    model_id=route.model_id,
                    provider_request_id=self._response_id(response),
                    token_usage=self._token_usage(response),
                    latency_ms=self._latency_ms(started_at),
                    completion_status="completed",
                    retry_count=retry_count,
                )

            incomplete_reason = self._incomplete_reason(choice)
            if incomplete_retries < self._config.incomplete_max_retries:
                incomplete_retries += 1
                await self._backoff(transient_retries + incomplete_retries)
                continue
            return StructuredModelResult[ModelOutputT](
                output=None,
                provider_alias=self.provider_alias,
                model_id=route.model_id,
                provider_request_id=self._response_id(response),
                token_usage=self._token_usage(response),
                latency_ms=self._latency_ms(started_at),
                completion_status="incomplete",
                incomplete_reason=incomplete_reason,
                retry_count=transient_retries + incomplete_retries,
            )

    async def _backoff(self, retry_number: int) -> None:
        delay = self._config.backoff_base_seconds * (2 ** (retry_number - 1))
        delay += self._config.backoff_jitter_seconds * self._random_value()
        await self._sleep(delay)

    @classmethod
    def _incomplete_result[OutputT: BaseModel](
        cls,
        *,
        route: QwenModelRoute,
        started_at: float,
        reason: str,
        retry_count: int,
    ) -> StructuredModelResult[OutputT]:
        return StructuredModelResult[OutputT](
            output=None,
            provider_alias=cls.provider_alias,
            model_id=route.model_id,
            latency_ms=cls._latency_ms(started_at),
            completion_status="incomplete",
            incomplete_reason=reason,
            retry_count=retry_count,
        )

    @staticmethod
    def _non_retryable(role: ModelRole) -> BriefParserError:
        return BriefParserError(
            ErrorCode.PROVIDER_OUTPUT_INVALID,
            "Qwen Provider 拒绝了无效请求、地域或配置。",
            details={"role": role.value},
        )

    @staticmethod
    def _first_choice(response: Any) -> Any | None:
        choices = getattr(response, "choices", None) or ()
        return choices[0] if choices else None

    @staticmethod
    def _parsed(choice: Any | None) -> Any | None:
        message = getattr(choice, "message", None)
        return getattr(message, "parsed", None)

    @staticmethod
    def _refusal(choice: Any | None) -> str | None:
        if getattr(choice, "finish_reason", None) == "content_filter":
            return "content_filter"
        message = getattr(choice, "message", None)
        refusal = getattr(message, "refusal", None)
        return refusal if isinstance(refusal, str) and refusal else None

    @staticmethod
    def _incomplete_reason(choice: Any | None) -> str:
        if choice is None:
            return "empty_choices"
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            return "max_completion_tokens"
        if isinstance(finish_reason, str) and finish_reason != "stop":
            return finish_reason
        return "schema_invalid"

    @staticmethod
    def _response_id(response: Any) -> str | None:
        value = getattr(response, "id", None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _token_usage(response: Any) -> TokenUsage:
        usage = getattr(response, "usage", None)
        return TokenUsage(
            input_tokens=max(0, int(getattr(usage, "prompt_tokens", 0) or 0)),
            output_tokens=max(0, int(getattr(usage, "completion_tokens", 0) or 0)),
        )

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1_000))
