from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from pydantic import Field

from brief_parser.adapters.bounded_provider import BoundedModelProvider
from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.ports.model_provider import (
    ModelOutputT,
    ModelRequestContext,
    ProviderMessage,
    StructuredModelResult,
)


class Candidate(StrictModel):
    items: list[str] = Field(default_factory=list)


class ConcurrencyProbeProvider:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def structured_generate(
        self,
        *,
        role: ModelRole,
        messages: Sequence[ProviderMessage],
        output_schema: type[ModelOutputT],
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ModelOutputT]:
        del messages
        del request_context
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            return StructuredModelResult[ModelOutputT](
                output=output_schema.model_validate({"items": [role.value]}),
                provider_alias="probe",
                model_id="probe-model",
            )
        finally:
            self.active -= 1


async def test_bounded_provider_queues_calls_at_configured_limit() -> None:
    probe = ConcurrencyProbeProvider()
    provider = BoundedModelProvider(probe, max_concurrency=2)
    context = ModelRequestContext(request_id="req_probe", trace_id="trace_probe")
    message = ProviderMessage(role="user", content="synthetic")

    results = await asyncio.gather(
        *(
            provider.structured_generate(
                role=ModelRole.EXTRACTOR,
                messages=[message],
                output_schema=Candidate,
                request_context=context,
            )
            for _ in range(8)
        )
    )

    assert probe.peak == 2
    assert all(result.output == Candidate(items=["extractor"]) for result in results)


def test_bounded_provider_rejects_nonpositive_limit() -> None:
    with pytest.raises(ValueError, match="max_concurrency must be positive"):
        BoundedModelProvider(ConcurrencyProbeProvider(), max_concurrency=0)
