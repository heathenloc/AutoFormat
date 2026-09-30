"""Request-level resource limits shared by every application entrypoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from brief_parser.domain.document import ExtractedDocument
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource


@dataclass(frozen=True, slots=True)
class ParseResourceLimits:
    max_sources: int = 10
    max_total_pdf_pages: int = 100
    max_total_extracted_chars: int = 250_000

    def __post_init__(self) -> None:
        if min(
            self.max_sources,
            self.max_total_pdf_pages,
            self.max_total_extracted_chars,
        ) <= 0:
            raise ValueError("parse resource limits must be positive")

    def validate_source_count(self, source_count: int) -> None:
        if source_count > self.max_sources:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "输入 Source 数量超过允许上限。",
                details={
                    "source_count": source_count,
                    "max_sources": self.max_sources,
                },
            )

    def validate_secured_sources(self, sources: Sequence[SecuredSource]) -> None:
        self.validate_source_count(len(sources))
        total_pdf_pages = sum(
            source.page_count or 0 for source in sources if source.kind == "pdf"
        )
        if total_pdf_pages > self.max_total_pdf_pages:
            raise BriefParserError(
                ErrorCode.SOURCE_TOO_MANY_PAGES,
                "本次请求的 PDF 合计页数超过允许上限。",
                details={
                    "total_pdf_pages": total_pdf_pages,
                    "max_total_pdf_pages": self.max_total_pdf_pages,
                },
            )

    def validate_documents(self, documents: Sequence[ExtractedDocument]) -> None:
        total_extracted_chars = sum(
            document.quality.extracted_char_count for document in documents
        )
        if total_extracted_chars > self.max_total_extracted_chars:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTED_TOO_LARGE,
                "本次请求提取后的合计字符数超过允许上限。",
                details={
                    "total_extracted_chars": total_extracted_chars,
                    "max_total_extracted_chars": self.max_total_extracted_chars,
                },
            )
