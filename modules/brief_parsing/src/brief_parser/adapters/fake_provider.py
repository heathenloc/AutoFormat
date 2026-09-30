"""Deterministic structured-output provider for tests and local development."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.model_provider import (
    ModelOutputT,
    ModelRequestContext,
    ProviderMessage,
    StructuredModelResult,
)


class FakeFailure(StrictModel):
    status: Literal["refused", "incomplete"]
    reason: str


type FakeResponse = BaseModel | Mapping[str, Any] | Exception | FakeFailure


class FakeModelProvider:
    """Return queued responses and still enforce the requested Pydantic schema."""

    provider_alias = "fake"

    def __init__(
        self,
        responses: Mapping[ModelRole, Iterable[FakeResponse]] | None = None,
        *,
        model_ids: Mapping[ModelRole, str] | None = None,
    ) -> None:
        self._responses: dict[ModelRole, deque[FakeResponse]] = defaultdict(deque)
        if responses is not None:
            for role, queued in responses.items():
                self._responses[role].extend(queued)
        self._model_ids = {} if model_ids is None else dict(model_ids)
        self.call_count: dict[ModelRole, int] = defaultdict(int)

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
        started_at = perf_counter()
        self.call_count[role] += 1
        if not self._responses[role]:
            return StructuredModelResult[ModelOutputT](
                output=None,
                provider_alias=self.provider_alias,
                model_id=self._model_ids.get(role, f"fake-{role.value}"),
                latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
                completion_status="incomplete",
                incomplete_reason="fake_provider_has_no_scripted_response",
            )

        candidate = self._responses[role].popleft()
        if isinstance(candidate, Exception):
            raise candidate
        if isinstance(candidate, FakeFailure):
            return StructuredModelResult[ModelOutputT](
                output=None,
                provider_alias=self.provider_alias,
                model_id=self._model_ids.get(role, f"fake-{role.value}"),
                latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
                completion_status=candidate.status,
                refusal_reason=(candidate.reason if candidate.status == "refused" else None),
                incomplete_reason=(candidate.reason if candidate.status == "incomplete" else None),
            )
        if isinstance(candidate, BaseModel):
            payload = candidate.model_dump(mode="python")
        else:
            payload = dict(candidate)
        try:
            output = output_schema.model_validate(payload)
        except ValidationError as exc:
            raise BriefParserError(
                ErrorCode.PROVIDER_OUTPUT_INVALID,
                "Fake Provider 输出无法通过内部 Schema。",
                details={"role": role.value},
            ) from exc
        latency_ms = max(0, int((perf_counter() - started_at) * 1000))
        return StructuredModelResult[ModelOutputT](
            output=output,
            provider_alias=self.provider_alias,
            model_id=self._model_ids.get(role, f"fake-{role.value}"),
            provider_request_id=None,
            latency_ms=latency_ms,
            completion_status="completed",
            retry_count=0,
        )
