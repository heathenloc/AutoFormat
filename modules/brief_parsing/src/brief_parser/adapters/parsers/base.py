"""Shared parser result types kept behind the ingestion adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from brief_parser.domain.document import BlockKind, BlockStyle, DocumentLocator
from brief_parser.ports.document_ingestion import SecuredSource, SourceKind


@dataclass(frozen=True, slots=True)
class BlockDraft:
    kind: BlockKind
    raw_text: str
    locator: DocumentLocator
    style: BlockStyle = field(default_factory=BlockStyle)


@dataclass(frozen=True, slots=True)
class ParserResult:
    parser_id: str
    parser_version: str
    drafts: tuple[BlockDraft, ...]
    page_count: int | None = None
    empty_page_count: int = 0
    duplicate_header_count: int = 0
    duplicate_footer_count: int = 0
    warnings: tuple[str, ...] = ()


class DocumentParser(Protocol):
    supported_kinds: frozenset[SourceKind]

    def parse(self, source: SecuredSource) -> ParserResult: ...

