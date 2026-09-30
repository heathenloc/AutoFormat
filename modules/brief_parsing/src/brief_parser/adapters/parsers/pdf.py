"""Text-layer PDF adapter with page locators and duplicate margin detection."""

from __future__ import annotations

import math
import re
from collections import Counter
from io import BytesIO

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from brief_parser.adapters.parsers.base import BlockDraft, ParserResult
from brief_parser.domain.document import BlockKind, DocumentLocator
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource, SourceKind


def _comparison_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PdfParser:
    supported_kinds: frozenset[SourceKind] = frozenset({"pdf"})
    parser_id = "pdf-pdfplumber"
    parser_version = "1.0.0"

    def parse(self, source: SecuredSource) -> ParserResult:
        if source.kind != "pdf":
            raise ValueError(f"unsupported source kind for PdfParser: {source.kind}")
        try:
            with pdfplumber.open(BytesIO(source.content)) as document:
                page_lines = [self._page_lines(page) for page in document.pages]
        except (PDFSyntaxError, ValueError, TypeError, OSError) as exc:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTION_FAILED,
                "PDF 文本层无法稳定提取。",
            ) from exc

        header_keys, footer_keys = self._repeated_margins(page_lines)
        seen_headers: set[str] = set()
        seen_footers: set[str] = set()
        duplicate_header_count = 0
        duplicate_footer_count = 0
        empty_page_count = sum(not lines for lines in page_lines)
        drafts: list[BlockDraft] = []

        for page_number, lines in enumerate(page_lines, start=1):
            for line_index, line in enumerate(lines, start=1):
                key = _comparison_key(line)
                is_header = line_index == 1 and key in header_keys
                is_footer = line_index == len(lines) and key in footer_keys and not is_header
                if is_header:
                    if key in seen_headers:
                        duplicate_header_count += 1
                        continue
                    seen_headers.add(key)
                    kind = BlockKind.HEADER
                elif is_footer:
                    if key in seen_footers:
                        duplicate_footer_count += 1
                        continue
                    seen_footers.add(key)
                    kind = BlockKind.FOOTER
                else:
                    kind = BlockKind.PARAGRAPH
                drafts.append(
                    BlockDraft(
                        kind=kind,
                        raw_text=line,
                        locator=DocumentLocator(
                            page=page_number,
                            paragraph=line_index,
                            section_path=(
                                ["header"]
                                if kind == BlockKind.HEADER
                                else ["footer"]
                                if kind == BlockKind.FOOTER
                                else []
                            ),
                        ),
                    )
                )

        warnings: list[str] = []
        if duplicate_header_count:
            warnings.append("DUPLICATE_HEADERS_REMOVED")
        if duplicate_footer_count:
            warnings.append("DUPLICATE_FOOTERS_REMOVED")
        return ParserResult(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            drafts=tuple(drafts),
            page_count=len(page_lines),
            empty_page_count=empty_page_count,
            duplicate_header_count=duplicate_header_count,
            duplicate_footer_count=duplicate_footer_count,
            warnings=tuple(warnings),
        )

    def _page_lines(self, page: object) -> list[str]:
        extracted = page.extract_text(x_tolerance=3, y_tolerance=3)  # type: ignore[attr-defined]
        if extracted is None:
            return []
        return [line for line in extracted.splitlines() if line.strip()]

    def _repeated_margins(
        self,
        page_lines: list[list[str]],
    ) -> tuple[set[str], set[str]]:
        if len(page_lines) < 3:
            return set(), set()
        threshold = max(2, math.ceil(len(page_lines) * 0.6))
        header_counts = Counter(
            _comparison_key(lines[0]) for lines in page_lines if lines
        )
        footer_counts = Counter(
            _comparison_key(lines[-1]) for lines in page_lines if lines
        )
        return (
            {key for key, count in header_counts.items() if key and count >= threshold},
            {key for key, count in footer_counts.items() if key and count >= threshold},
        )

