"""Versioned prompt repository port."""

from __future__ import annotations

from typing import Annotated, Protocol

from pydantic import Field

from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole


class PromptTemplate(StrictModel):
    role: ModelRole
    version: Annotated[str, Field(pattern=r"^(extractor|auditor|resolver)/v[1-9]\d*$")]
    content: Annotated[str, Field(min_length=1)]


class PromptRepository(Protocol):
    def get(self, *, role: ModelRole, version: str) -> PromptTemplate:
        """Load one immutable prompt template by exact role and version."""
