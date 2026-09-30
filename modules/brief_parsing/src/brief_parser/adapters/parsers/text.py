"""UTF-8 text and direct-text adapters."""

from __future__ import annotations

import re

from brief_parser.adapters.parsers.base import BlockDraft, ParserResult
from brief_parser.domain.document import BlockKind, BlockStyle, DocumentLocator
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource, SourceKind

_HEADING = re.compile(r"^(?P<indent>\s*)(?P<marks>#{1,6})\s+\S")
_LIST_ITEM = re.compile(
    r"^(?P<indent>\s*)(?:[-*+]\s+|\d+[.)]\s+|[一二三四五六七八九十]+[、.]\s*)\S"
)


class TextParser:
    supported_kinds: frozenset[SourceKind] = frozenset({"text", "txt"})
    parser_version = "1.0.0"

    def parse(self, source: SecuredSource) -> ParserResult:
        if source.kind not in self.supported_kinds:
            raise ValueError(f"unsupported source kind for TextParser: {source.kind}")
        try:
            text = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BriefParserError(
                ErrorCode.SOURCE_TEXT_ENCODING,
                "文本无法按 UTF-8 解码。",
            ) from exc

        has_pages = "\f" in text
        drafts: list[BlockDraft] = []
        page = 1
        paragraph = 0
        section_titles: dict[int, str] = {}
        for chunk in re.split(r"(\f)", text):
            if chunk == "\f":
                drafts.append(
                    BlockDraft(
                        kind=BlockKind.PAGE_BREAK,
                        raw_text="\f",
                        locator=DocumentLocator(page=page if has_pages else None),
                    )
                )
                page += 1
                paragraph = 0
                section_titles.clear()
                continue
            for line in re.split(r"\r\n|\r|\n", chunk):
                if not line.strip():
                    continue
                paragraph += 1
                heading_match = _HEADING.match(line)
                list_match = _LIST_ITEM.match(line)
                if heading_match is not None:
                    heading_level = len(heading_match.group("marks"))
                    title = line[heading_match.end("marks") :].strip()
                    for level in tuple(section_titles):
                        if level >= heading_level:
                            del section_titles[level]
                    section_titles[heading_level] = title
                    kind = BlockKind.HEADING
                    style = BlockStyle(heading_level=heading_level, bold_ratio=0.0)
                elif list_match is not None:
                    indentation = len(list_match.group("indent").expandtabs(4))
                    kind = BlockKind.LIST_ITEM
                    style = BlockStyle(list_level=indentation // 2, bold_ratio=0.0)
                else:
                    kind = BlockKind.PARAGRAPH
                    style = BlockStyle()
                drafts.append(
                    BlockDraft(
                        kind=kind,
                        raw_text=line,
                        locator=DocumentLocator(
                            page=page if has_pages else None,
                            paragraph=paragraph,
                            section_path=[
                                section_titles[level] for level in sorted(section_titles)
                            ],
                        ),
                        style=style,
                    )
                )
        return ParserResult(
            parser_id="direct-text" if source.kind == "text" else "txt-utf8",
            parser_version=self.parser_version,
            drafts=tuple(drafts),
            page_count=page if has_pages else None,
        )

