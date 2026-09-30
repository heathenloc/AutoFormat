from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APITimeoutError, RateLimitError
from pydantic import Field, SecretStr

from brief_parser.adapters.openai_provider import (
    OpenAIModelProvider,
    OpenAIModelRoute,
    OpenAIProviderConfig,
)
from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.model_provider import ModelRequestContext, ProviderMessage


class SampleOutput(StrictModel):
    items: list[str] = Field(default_factory=list)


class StubResponses:
    def __init__(self, responses: list[object]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        candidate = self.responses.popleft()
        if isinstance(candidate, Exception):
            raise candidate
        return candidate


class StubClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = StubResponses(responses)


def _config(**overrides: object) -> OpenAIProviderConfig:
    values: dict[str, object] = {
        "api_key": SecretStr("synthetic-key"),
        "routes": {
            ModelRole.EXTRACTOR: OpenAIModelRoute(
                model_id="gpt-5.6-terra",
                reasoning_effort="low",
            ),
            ModelRole.AUDITOR: OpenAIModelRoute(
                model_id="gpt-5.6-luna",
                reasoning_effort="low",
            ),
            ModelRole.RESOLVER: OpenAIModelRoute(
                model_id="gpt-5.6-sol",
                reasoning_effort="medium",
            ),
        },
        "backoff_base_seconds": 0,
        "backoff_jitter_seconds": 0,
    }
    values.update(overrides)
    return OpenAIProviderConfig.model_validate(values)


def _context() -> ModelRequestContext:
    return ModelRequestContext(
        request_id="req_sample",
        trace_id="trace_sample",
        source_ids=["src_sample"],
    )


def _response(
    *,
    status: str = "completed",
    output_parsed: object = None,
    output: list[object] | None = None,
    incomplete_reason: str | None = None,
) -> object:
    return SimpleNamespace(
        id="resp_sample",
        status=status,
        output_parsed=output_parsed,
        output=[] if output is None else output,
        incomplete_details=(
            None if incomplete_reason is None else SimpleNamespace(reason=incomplete_reason)
        ),
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


async def test_openai_provider_uses_responses_structured_output_without_tools() -> None:
    client = StubClient([_response(output_parsed={"items": ["synthetic"]})])
    provider = OpenAIModelProvider(_config(), client=client)

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output == SampleOutput(items=["synthetic"])
    assert result.provider_request_id == "resp_sample"
    assert result.token_usage.input_tokens == 11
    call = client.responses.calls[0]
    assert call["store"] is False
    assert call["text_format"] is SampleOutput
    assert call["reasoning"] == {"effort": "low"}
    assert "tools" not in call
    assert "synthetic-key" not in repr(provider)


async def test_openai_provider_returns_refusal_without_retry() -> None:
    refusal = SimpleNamespace(type="refusal", refusal="safety_refusal")
    message = SimpleNamespace(type="message", content=[refusal])
    client = StubClient([_response(output=[message])])
    provider = OpenAIModelProvider(_config(), client=client)

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.completion_status == "refused"
    assert result.output is None
    assert result.refusal_reason == "safety_refusal"
    assert len(client.responses.calls) == 1


async def test_openai_provider_retries_timeout_then_returns_safe_error() -> None:
    timeout = APITimeoutError(httpx2.Request("POST", "https://api.openai.com/v1/responses"))
    client = StubClient([timeout, timeout, timeout])
    waits: list[float] = []

    async def record_wait(delay: float) -> None:
        waits.append(delay)

    provider = OpenAIModelProvider(_config(), client=client, sleep=record_wait)

    with pytest.raises(BriefParserError) as error:
        await provider.structured_generate(
            role=ModelRole.EXTRACTOR,
            messages=[ProviderMessage(role="user", content="synthetic source")],
            output_schema=SampleOutput,
            request_context=_context(),
        )

    assert error.value.code == ErrorCode.PROVIDER_TRANSIENT
    assert error.value.retryable is True
    assert len(client.responses.calls) == 3
    assert waits == [0.0, 0.0]


async def test_openai_provider_retries_rate_limit_then_succeeds() -> None:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(429, request=request)
    rate_limit = RateLimitError(
        "synthetic rate limit",
        response=response,
        body={"error": {"message": "synthetic"}},
    )
    client = StubClient(
        [rate_limit, _response(output_parsed={"items": ["recovered"]})]
    )
    waits: list[float] = []

    async def record_wait(delay: float) -> None:
        waits.append(delay)

    provider = OpenAIModelProvider(_config(), client=client, sleep=record_wait)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output == SampleOutput(items=["recovered"])
    assert result.retry_count == 1
    assert len(client.responses.calls) == 2
    assert waits == [0.0]


async def test_openai_provider_retries_one_incomplete_structured_output() -> None:
    client = StubClient(
        [
            _response(status="incomplete", incomplete_reason="max_output_tokens"),
            _response(output_parsed={"items": ["verified"]}),
        ]
    )

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = OpenAIModelProvider(_config(), client=client, sleep=no_wait)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.completion_status == "completed"
    assert result.retry_count == 1
    assert len(client.responses.calls) == 2


async def test_openai_provider_returns_incomplete_after_single_safe_retry() -> None:
    client = StubClient(
        [
            _response(status="incomplete", incomplete_reason="max_output_tokens"),
            _response(status="incomplete", incomplete_reason="max_output_tokens"),
        ]
    )

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = OpenAIModelProvider(_config(), client=client, sleep=no_wait)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.completion_status == "incomplete"
    assert result.output is None
    assert result.incomplete_reason == "max_output_tokens"
    assert result.retry_count == 1


async def test_openai_provider_rejects_repeated_internal_schema_failure() -> None:
    client = StubClient(
        [
            _response(output_parsed={"items": "not-a-list"}),
            _response(output_parsed={"items": "still-not-a-list"}),
        ]
    )

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = OpenAIModelProvider(_config(), client=client, sleep=no_wait)

    with pytest.raises(BriefParserError) as error:
        await provider.structured_generate(
            role=ModelRole.EXTRACTOR,
            messages=[ProviderMessage(role="user", content="synthetic source")],
            output_schema=SampleOutput,
            request_context=_context(),
        )

    assert error.value.code == ErrorCode.PROVIDER_OUTPUT_INVALID
    assert len(client.responses.calls) == 2


def test_openai_provider_config_never_serializes_api_key() -> None:
    config = _config()

    assert "synthetic-key" not in config.model_dump_json()
    assert "synthetic-key" not in repr(config)
