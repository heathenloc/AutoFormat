"""Shared ingestion facade routing secured sources through one block pipeline."""

from __future__ import annotations

from collections.abc import Iterable

from brief_parser.adapters.block_builder import BlockBuilder
from brief_parser.adapters.parsers.base import DocumentParser
from brief_parser.adapters.parsers.docx import DocxParser
from brief_parser.adapters.parsers.pdf import PdfParser
from brief_parser.adapters.parsers.text import TextParser
from brief_parser.adapters.quality_gate import ExtractionQualityGate
from brief_parser.domain.document import ExtractedDocument
from brief_parser.domain.requirement_ir import SourceManifest
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource, SourceKind


class DocumentIngestor:
    def __init__(
        self,
        parsers: Iterable[DocumentParser] | None = None,
        *,
        block_builder: BlockBuilder | None = None,
        quality_gate: ExtractionQualityGate | None = None,
    ) -> None:
        configured: list[DocumentParser] = (
            [TextParser(), DocxParser(), PdfParser()]
            if parsers is None
            else list(parsers)
        )
        self._parsers: dict[SourceKind, DocumentParser] = {}
        for parser in configured:
            for kind in parser.supported_kinds:
                if kind in self._parsers:
                    raise ValueError(f"multiple parsers registered for source kind {kind!r}")
                self._parsers[kind] = parser
        self._block_builder = BlockBuilder() if block_builder is None else block_builder
        self._quality_gate = (
            ExtractionQualityGate() if quality_gate is None else quality_gate
        )

    def ingest(self, source: SecuredSource) -> ExtractedDocument:
        parser = self._parsers.get(source.kind)
        if parser is None:
            raise BriefParserError(
                ErrorCode.SOURCE_UNSUPPORTED,
                "没有可处理该输入类型的 Parser。",
            )
        parser_result = parser.parse(source)
        blocks, normalization_maps = self._block_builder.build(
            source_id=source.source_id,
            drafts=parser_result.drafts,
        )
        quality = self._quality_gate.evaluate(
            source=source,
            parser_result=parser_result,
            blocks=blocks,
        )
        warning_codes = [
            *source.security_warnings,
            *parser_result.warnings,
            *(warning.code for warning in quality.warnings),
        ]
        manifest = SourceManifest(
            source_id=source.source_id,
            client_source_id=source.client_source_id,
            kind=source.kind,
            filename=source.filename,
            media_type=source.media_type,
            byte_size=source.byte_size,
            sha256=source.sha256,
            language_hints=list(source.language_hints),
            parser_id=parser_result.parser_id,
            parser_version=parser_result.parser_version,
            extraction_status="complete",
            warnings=list(dict.fromkeys(warning_codes)),
        )
        return ExtractedDocument(
            source_manifest=manifest,
            blocks=blocks,
            normalization_maps=normalization_maps,
            quality=quality,
        )
