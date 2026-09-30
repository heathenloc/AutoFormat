from types import SimpleNamespace

import httpx2
import pytest
from openai import ContentFilterFinishReasonError, RateLimitError
from pydantic import BaseModel, ValidationError

from brief_parser.adapters.qwen_provider import (
    QWEN_BEIJING_BASE_URL,
    QWEN_FIXED_MODEL_ID,
    QwenModelProvider,
    QwenModelRoute,
    QwenProviderConfig,
)
from brief_parser.bootstrap import build_model_provider
from brief_parser.config import Settings
from brief_parser.domain.enums import ModelRole
from brief_parser.ports.model_provider import ModelRequestContext, ProviderMessage


class SampleOutput(BaseModel):
    items: list[str]


class StubCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StubClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=StubCompletions(outcomes))


def _response(
    *,
    parsed: object | None = None,
    finish_reason: str = "stop",
    refusal: str | None = None,
) -> object:
    return SimpleNamespace(
        id="chatcmpl-synthetic",
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(parsed=parsed, refusal=refusal),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
    )


def _config(**overrides: object) -> QwenProviderConfig:
    values: dict[str, object] = {
        "api_key": "synthetic-key",
        "base_url": QWEN_BEIJING_BASE_URL,
        "routes": {
            role: QwenModelRoute(
                model_id=QWEN_FIXED_MODEL_ID,
                enable_thinking=False,
            )
            for role in ModelRole
        },
        "backoff_base_seconds": 0,
        "backoff_jitter_seconds": 0,
    }
    values.update(overrides)
    return QwenProviderConfig.model_validate(values)


def _context() -> ModelRequestContext:
    return ModelRequestContext(
        request_id="req_qwen_test",
        trace_id="trace_qwen_test",
    )


async def test_qwen_provider_uses_fixed_chat_parse_contract() -> None:
    client = StubClient([_response(parsed={"items": ["verified"]})])
    provider = QwenModelProvider(_config(), client=client)

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[
            ProviderMessage(role="system", content="Return structured facts."),
            ProviderMessage(role="user", content="Synthetic source."),
        ],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output == SampleOutput(items=["verified"])
    assert result.provider_alias == "qwen"
    assert result.model_id == QWEN_FIXED_MODEL_ID
    assert result.provider_request_id == "chatcmpl-synthetic"
    assert result.token_usage.input_tokens == 20
    assert result.token_usage.output_tokens == 5
    call = client.chat.completions.calls[0]
    assert call["model"] == QWEN_FIXED_MODEL_ID
    assert call["response_format"] is SampleOutput
    assert call["extra_body"] == {"enable_thinking": False}
    assert call["temperature"] == 0.0
    assert call["max_completion_tokens"] == 8_000
    assert "tools" not in call


async def test_qwen_provider_retries_rate_limit_then_succeeds() -> None:
    request = httpx2.Request(
        "POST",
        f"{QWEN_BEIJING_BASE_URL}/chat/completions",
    )
    response = httpx2.Response(429, request=request)
    rate_limit = RateLimitError(
        "synthetic rate limit",
        response=response,
        body={"error": {"message": "synthetic"}},
    )
    client = StubClient(
        [rate_limit, _response(parsed={"items": ["recovered"]})]
    )
    waits: list[float] = []

    async def record_wait(delay: float) -> None:
        waits.append(delay)

    provider = QwenModelProvider(_config(), client=client, sleep=record_wait)
    result = await provider.structured_generate(
        role=ModelRole.AUDITOR,
        messages=[ProviderMessage(role="user", content="Synthetic source.")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output == SampleOutput(items=["recovered"])
    assert result.retry_count == 1
    assert waits == [0.0]


async def test_qwen_provider_maps_content_filter_to_refusal() -> None:
    client = StubClient([ContentFilterFinishReasonError()])
    provider = QwenModelProvider(_config(), client=client)

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="Synthetic source.")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.completion_status == "refused"
    assert result.output is None
    assert result.refusal_reason == "content_filter"


async def test_qwen_provider_retries_schema_failure_then_returns_incomplete() -> None:
    client = StubClient(
        [
            _response(parsed={"items": "not-a-list"}),
            _response(parsed={"items": "still-not-a-list"}),
        ]
    )

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = QwenModelProvider(_config(), client=client, sleep=no_wait)

    result = await provider.structured_generate(
        role=ModelRole.RESOLVER,
        messages=[ProviderMessage(role="user", content="Synthetic source.")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output is None
    assert result.completion_status == "incomplete"
    assert result.incomplete_reason == "schema_invalid"
    assert result.provider_request_id == "chatcmpl-synthetic"
    assert result.token_usage.input_tokens == 20
    assert result.retry_count == 1
    assert len(client.chat.completions.calls) == 2


async def test_qwen_provider_handles_sdk_parse_validation_error_without_crashing() -> None:
    with pytest.raises(ValidationError) as captured:
        SampleOutput.model_validate({"items": "not-a-list"})
    client = StubClient([captured.value, captured.value])

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = QwenModelProvider(_config(), client=client, sleep=no_wait)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="Synthetic source.")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.output is None
    assert result.completion_status == "incomplete"
    assert result.incomplete_reason == "schema_invalid"
    assert result.retry_count == 1
    assert len(client.chat.completions.calls) == 2


async def test_qwen_provider_returns_incomplete_for_repeated_length_finish() -> None:
    client = StubClient(
        [
            _response(finish_reason="length"),
            _response(finish_reason="length"),
        ]
    )

    async def no_wait(delay: float) -> None:
        assert delay == 0

    provider = QwenModelProvider(_config(), client=client, sleep=no_wait)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="Synthetic source.")],
        output_schema=SampleOutput,
        request_context=_context(),
    )

    assert result.completion_status == "incomplete"
    assert result.incomplete_reason == "max_completion_tokens"
    assert result.retry_count == 1


def test_qwen_config_rejects_non_compatible_or_insecure_endpoint() -> None:
    for endpoint in (
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com/api/v1",
        "https://user:pass@dashscope.aliyuncs.com/compatible-mode/v1",
        "https://attacker.example/compatible-mode/v1",
    ):
        with pytest.raises(ValidationError, match="compatible-mode/v1"):
            _config(base_url=endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
        "https://trial.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    ],
)
def test_qwen_config_accepts_official_regional_endpoints(endpoint: str) -> None:
    assert _config(base_url=endpoint).base_url == endpoint


def test_qwen_config_never_serializes_api_key_or_base_url() -> None:
    config = _config()

    serialized = config.model_dump_json()
    rendered = repr(config)
    assert "synthetic-key" not in serialized
    assert "synthetic-key" not in rendered
    assert QWEN_BEIJING_BASE_URL not in serialized
    assert QWEN_BEIJING_BASE_URL not in rendered


def test_bootstrap_builds_qwen_provider_without_network_call() -> None:
    settings = Settings.from_env(
        {
            "BRIEF_PARSER_PROVIDER": "qwen",
            "DASHSCOPE_API_KEY": "synthetic-key",
        }
    )

    provider = build_model_provider(settings)

    assert isinstance(provider, QwenModelProvider)
