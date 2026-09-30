"""Ports and immutable in-memory types for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from brief_parser.domain.document import ExtractedDocument

type SourceKind = Literal["text", "txt", "docx", "pdf"]


@dataclass(frozen=True, slots=True)
class SecuredSource:
    source_id: str
    client_source_id: str
    kind: SourceKind
    filename: str | None
    media_type: str
    content: bytes
    byte_size: int
    sha256: str
    language_hints: tuple[str, ...] = ()
    page_count: int | None = None
    security_warnings: tuple[str, ...] = ()


class InputSecurityPort(Protocol):
    def secure_file(
        self,
        path: Path,
        *,
        source_id: str,
        client_source_id: str,
        media_type: str | None = None,
        language_hints: tuple[str, ...] = (),
    ) -> SecuredSource: ...

    def secure_text(
        self,
        text: str,
        *,
        source_id: str,
        client_source_id: str,
        language_hints: tuple[str, ...] = (),
    ) -> SecuredSource: ...


class DocumentIngestionPort(Protocol):
    def ingest(self, source: SecuredSource) -> ExtractedDocument: ...

