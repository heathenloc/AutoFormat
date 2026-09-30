import pytest
from pydantic import Field

from brief_parser.adapters.fake_provider import FakeFailure, FakeModelProvider
from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.model_provider import ModelRequestContext, ProviderMessage


class Candidate(StrictModel):
    items: list[str] = Field(default_factory=list)


async def test_fake_provider_validates_queued_output() -> None:
    provider = FakeModelProvider(
        {ModelRole.EXTRACTOR: [{"items": ["synthetic requirement"]}]}
    )

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=Candidate,
        request_context=ModelRequestContext(
            request_id="req_sample",
            trace_id="trace_sample",
            source_ids=["src_sample"],
        ),
    )

    assert result.output == Candidate(items=["synthetic requirement"])
    assert result.provider_alias == "fake"
    assert provider.call_count[ModelRole.EXTRACTOR] == 1


async def test_fake_provider_can_simulate_refusal() -> None:
    provider = FakeModelProvider(
        {ModelRole.EXTRACTOR: [FakeFailure(status="refused", reason="synthetic_refusal")]}
    )

    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[ProviderMessage(role="user", content="synthetic source")],
        output_schema=Candidate,
        request_context=ModelRequestContext(
            request_id="req_sample",
            trace_id="trace_sample",
        ),
    )

    assert result.completion_status == "refused"
    assert result.output is None
    assert result.refusal_reason == "synthetic_refusal"


async def test_fake_provider_wraps_invalid_schema_output() -> None:
    provider = FakeModelProvider({ModelRole.EXTRACTOR: [{"items": "invalid"}]})

    with pytest.raises(BriefParserError) as error:
        await provider.structured_generate(
            role=ModelRole.EXTRACTOR,
            messages=[ProviderMessage(role="user", content="synthetic source")],
            output_schema=Candidate,
            request_context=ModelRequestContext(
                request_id="req_sample",
                trace_id="trace_sample",
            ),
        )

    assert error.value.code == ErrorCode.PROVIDER_OUTPUT_INVALID
