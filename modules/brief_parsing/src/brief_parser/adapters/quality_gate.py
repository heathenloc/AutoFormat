"""Deterministic extraction quality gate executed before any model call."""

from __future__ import annotations

import unicodedata

from brief_parser.adapters.parsers.base import ParserResult
from brief_parser.domain.document import (
    BlockKind,
    DocumentBlock,
    ExtractionQuality,
    ExtractionQualityStatus,
    ExtractionWarning,
)
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource

_WARNING_MESSAGES = {
    "DOCX_EMBEDDED_OBJECT_IGNORED": "DOCX 中的嵌入对象未读取。",
    "DOCX_EXTERNAL_RELATIONSHIP_IGNORED": "DOCX 中的外部链接未访问。",
    "DUPLICATE_HEADERS_REMOVED": "已移除重复页眉副本。",
    "DUPLICATE_FOOTERS_REMOVED": "已移除重复页脚副本。",
    "PDF_EMPTY_PAGES": "PDF 包含没有可靠文本层的页面。",
    "OVERLONG_BLOCKS": "文档包含异常长的文本块。",
    "REPLACEMENT_CHARACTERS": "提取文本包含 Unicode 替换字符。",
}


class ExtractionQualityGate:
    def __init__(
        self,
        *,
        max_extracted_chars: int = 250_000,
        overlong_block_chars: int = 20_000,
        max_replacement_ratio: float = 0.01,
        max_control_ratio: float = 0.01,
    ) -> None:
        if max_extracted_chars <= 0 or overlong_block_chars <= 0:
            raise ValueError("quality gate character limits must be positive")
        self.max_extracted_chars = max_extracted_chars
        self.overlong_block_chars = overlong_block_chars
        self.max_replacement_ratio = max_replacement_ratio
        self.max_control_ratio = max_control_ratio

    def evaluate(
        self,
        *,
        source: SecuredSource,
        parser_result: ParserResult,
        blocks: list[DocumentBlock],
    ) -> ExtractionQuality:
        extracted_text = "".join(
            block.normalized_text
            for block in blocks
            if block.kind != BlockKind.PAGE_BREAK
        )
        extracted_char_count = len(extracted_text)
        if extracted_char_count > self.max_extracted_chars:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTED_TOO_LARGE,
                "提取后的字符数超过允许上限。",
                details={"max_extracted_chars": self.max_extracted_chars},
            )
        meaningful_char_count = sum(not char.isspace() for char in extracted_text)
        if meaningful_char_count == 0:
            code = (
                ErrorCode.SOURCE_SCANNED_PDF
                if source.kind == "pdf"
                else ErrorCode.SOURCE_EXTRACTION_QUALITY
            )
            raise BriefParserError(
                code,
                "文档没有可可靠使用的文本，请提供原始可编辑文件或粘贴文本。",
            )

        page_count = parser_result.page_count
        if source.kind == "pdf" and page_count is not None:
            if source.page_count is not None and source.page_count != page_count:
                raise BriefParserError(
                    ErrorCode.SOURCE_PDF_INVALID,
                    "PDF 页数在安全检查与文本提取阶段不一致。",
                )
            empty_ratio = parser_result.empty_page_count / page_count
            if empty_ratio >= 0.5 or meaningful_char_count < page_count * 10:
                raise BriefParserError(
                    ErrorCode.SOURCE_SCANNED_PDF,
                    "PDF 没有可靠文本层，请提供原始文件或粘贴文本。",
                )

        replacement_count = extracted_text.count("\ufffd")
        replacement_ratio = replacement_count / extracted_char_count
        if replacement_ratio > self.max_replacement_ratio:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTION_QUALITY,
                "提取文本包含过多无法识别字符。",
            )

        suspicious_control_count = sum(
            unicodedata.category(char).startswith("C")
            and char not in {"\t", "\n", "\r", "\f"}
            for char in extracted_text
        )
        control_ratio = suspicious_control_count / extracted_char_count
        if control_ratio > self.max_control_ratio:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTION_QUALITY,
                "提取文本包含过多异常控制字符。",
            )

        warning_codes = [*source.security_warnings, *parser_result.warnings]
        if parser_result.empty_page_count:
            warning_codes.append("PDF_EMPTY_PAGES")
        overlong_block_count = sum(
            len(block.normalized_text) > self.overlong_block_chars for block in blocks
        )
        if overlong_block_count:
            warning_codes.append("OVERLONG_BLOCKS")
        if replacement_count:
            warning_codes.append("REPLACEMENT_CHARACTERS")
        warning_codes = list(dict.fromkeys(warning_codes))
        warnings = [
            ExtractionWarning(
                code=code,
                message=_WARNING_MESSAGES.get(code, "文档提取包含非阻断警告。"),
            )
            for code in warning_codes
        ]
        return ExtractionQuality(
            status=(
                ExtractionQualityStatus.WARNING
                if warnings
                else ExtractionQualityStatus.PASS
            ),
            page_count=page_count,
            empty_page_count=parser_result.empty_page_count,
            extracted_char_count=extracted_char_count,
            replacement_character_ratio=replacement_ratio,
            suspicious_control_ratio=control_ratio,
            duplicate_header_count=parser_result.duplicate_header_count,
            duplicate_footer_count=parser_result.duplicate_footer_count,
            overlong_block_count=overlong_block_count,
            warnings=warnings,
        )

