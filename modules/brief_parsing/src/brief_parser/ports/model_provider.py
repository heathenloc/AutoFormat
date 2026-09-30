"""Provider-neutral structured model generation port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Protocol, Self, TypeVar

from pydantic import BaseModel, Field, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.domain.enums import ModelRole

ModelOutputT = TypeVar("ModelOutputT", bound=BaseModel)


class ProviderMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1)]


class ModelRequestContext(StrictModel):
    request_id: Identifier
    trace_id: Identifier
    source_ids: list[Identifier] = Field(default_factory=list)


class TokenUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class StructuredModelResult[OutputT: BaseModel](StrictModel):
    output: OutputT | None
    provider_alias: Identifier
    model_id: Identifier
    provider_request_id: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    completion_status: Literal["completed", "refused", "incomplete"] = "completed"
    refusal_reason: str | None = None
    incomplete_reason: str | None = None
    retry_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.completion_status == "completed":
            if self.output is None:
                raise ValueError("completed provider results require output")
            if self.refusal_reason is not None or self.incomplete_reason is not None:
                raise ValueError("completed provider results cannot include failure reasons")
        elif self.completion_status == "refused":
            if self.output is not None or not self.refusal_reason:
                raise ValueError("refused provider results require only refusal_reason")
        elif self.output is not None or not self.incomplete_reason:
            raise ValueError("incomplete provider results require only incomplete_reason")
        return self


class ModelProvider(Protocol):
    async def structured_generate(
        self,
        *,
        role: ModelRole,
        messages: Sequence[ProviderMessage],
        output_schema: type[ModelOutputT],
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ModelOutputT]:
        """Generate and validate a structured result without exposing SDK types."""
