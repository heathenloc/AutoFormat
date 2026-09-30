"""Concurrency guard for provider-neutral structured generation."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from brief_parser.domain.enums import ModelRole
from brief_parser.ports.model_provider import (
    ModelOutputT,
    ModelProvider,
    ModelRequestContext,
    ProviderMessage,
    StructuredModelResult,
)


class BoundedModelProvider:
    """Queue Provider calls behind a process-local concurrency semaphore."""

    def __init__(self, provider: ModelProvider, *, max_concurrency: int) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._provider = provider
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def structured_generate(
        self,
        *,
        role: ModelRole,
        messages: Sequence[ProviderMessage],
        output_schema: type[ModelOutputT],
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ModelOutputT]:
        async with self._semaphore:
            return await self._provider.structured_generate(
                role=role,
                messages=messages,
                output_schema=output_schema,
                request_context=request_context,
            )
