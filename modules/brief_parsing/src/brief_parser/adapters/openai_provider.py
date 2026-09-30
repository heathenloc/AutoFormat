"""OpenAI Responses API adapter with bounded retries and structured validation."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any, Literal, Protocol, cast

import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from pydantic import Field, SecretStr, ValidationError, model_validator

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

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
Sleep = Callable[[float], Awaitable[None]]


class OpenAIModelRoute(StrictModel):
    model_id: Identifier
    reasoning_effort: ReasoningEffort
    max_output_tokens: int = Field(default=8_000, gt=0)


class OpenAIProviderConfig(StrictModel):
    api_key: SecretStr = Field(exclude=True, repr=False)
    routes: Mapping[ModelRole, OpenAIModelRoute]
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=90.0, gt=0)
    transient_max_retries: int = Field(default=2, ge=0, le=5)
    incomplete_max_retries: int = Field(default=1, ge=0, le=2)
    backoff_base_seconds: float = Field(default=0.25, ge=0)
    backoff_jitter_seconds: float = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def require_online_routes(self) -> OpenAIProviderConfig:
        required = {ModelRole.EXTRACTOR, ModelRole.AUDITOR, ModelRole.RESOLVER}
        missing = required - set(self.routes)
        if missing:
            missing_names = sorted(item.value for item in missing)
            raise ValueError(f"missing OpenAI model routes: {missing_names}")
        return self


class _ResponsesAPI(Protocol):
    async def parse(self, **kwargs: Any) -> Any:
        """Call Responses API structured parsing."""


class _OpenAIClient(Protocol):
    @property
    def responses(self) -> _ResponsesAPI:
        """Return the Responses API resource."""


class OpenAIModelProvider:
    provider_alias = "openai"

    def __init__(
        self,
        config: OpenAIProviderConfig,
        *,
        client: _OpenAIClient | None = None,
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
                timeout=timeout,
                max_retries=0,
            )
        self._client = cast(_OpenAIClient, configured_client)

    async def structured_generate(
        self,
        *,
        role: ModelRole,
        messages: Sequence[ProviderMessage],
        output_schema: type[ModelOutputT],
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ModelOutputT]:
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
                response = await self._client.responses.parse(
                    model=route.model_id,
                    input=[
                        {"role": message.role, "content": message.content}
                        for message in messages
                    ],
                    text_format=output_schema,
                    store=False,
                    reasoning={"effort": route.reasoning_effort},
                    max_output_tokens=route.max_output_tokens,
                    metadata={
                        "brief_request_id": request_context.request_id,
                        "trace_id": request_context.trace_id,
                    },
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
                        "模型 Provider 暂时不可用，请稍后重试。",
                        retryable=True,
                        details={"role": role.value, "retry_count": transient_retries},
                    ) from exc
                transient_retries += 1
                await self._backoff(transient_retries)
                continue
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
            refusal = self._refusal(response)
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

            parsed = getattr(response, "output_parsed", None)
            status = str(getattr(response, "status", "completed"))
            try:
                output = None if parsed is None else output_schema.model_validate(parsed)
            except ValidationError:
                output = None
                status = "schema_invalid"

            if status == "completed" and output is not None:
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

            incomplete_reason = self._incomplete_reason(response, fallback=status)
            if incomplete_retries < self._config.incomplete_max_retries:
                incomplete_retries += 1
                await self._backoff(transient_retries + incomplete_retries)
                continue
            if status == "schema_invalid":
                raise BriefParserError(
                    ErrorCode.PROVIDER_OUTPUT_INVALID,
                    "模型 Provider 返回了无法通过内部 Schema 的输出。",
                    details={"role": role.value, "retry_count": retry_count},
                )
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

    @staticmethod
    def _non_retryable(role: ModelRole) -> BriefParserError:
        return BriefParserError(
            ErrorCode.PROVIDER_OUTPUT_INVALID,
            "模型 Provider 拒绝了无效请求或配置。",
            details={"role": role.value},
        )

    @staticmethod
    def _response_id(response: Any) -> str | None:
        value = getattr(response, "id", None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _token_usage(response: Any) -> TokenUsage:
        usage = getattr(response, "usage", None)
        return TokenUsage(
            input_tokens=max(0, int(getattr(usage, "input_tokens", 0) or 0)),
            output_tokens=max(0, int(getattr(usage, "output_tokens", 0) or 0)),
        )

    @staticmethod
    def _refusal(response: Any) -> str | None:
        for output in getattr(response, "output", ()) or ():
            for item in getattr(output, "content", ()) or ():
                if getattr(item, "type", None) == "refusal":
                    reason = getattr(item, "refusal", None)
                    return reason if isinstance(reason, str) and reason else "provider_refusal"
        return None

    @staticmethod
    def _incomplete_reason(response: Any, *, fallback: str) -> str:
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        return reason if isinstance(reason, str) and reason else fallback

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1_000))
