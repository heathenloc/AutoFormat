"""Document extraction contracts shared by every input adapter."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from brief_parser.domain.base import Identifier, RawTextModel, Sha256Hex, StrictModel
from brief_parser.domain.requirement_ir import SourceManifest

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    PAGE_BREAK = "page_break"


class NormalizationKind(StrEnum):
    IDENTITY = "identity"
    NORMALIZED = "normalized"
    COLLAPSED_WHITESPACE = "collapsed_whitespace"


class ExtractionQualityStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    REJECT = "reject"


class DocumentLocator(StrictModel):
    page: PositiveInt | None = None
    paragraph: PositiveInt | None = None
    table: PositiveInt | None = None
    row: PositiveInt | None = None
    column: PositiveInt | None = None
    section: PositiveInt | None = None
    footnote: PositiveInt | None = None
    section_path: list[str] = Field(default_factory=list)


class InlineStyleSpan(StrictModel):
    start: NonNegativeInt
    end: PositiveInt
    bold: bool = False
    italic: bool = False
    underline: bool = False
    style_name: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end <= self.start:
            raise ValueError("inline style end must be greater than start")
        return self


class BlockStyle(StrictModel):
    heading_level: Annotated[int, Field(ge=1, le=9)] | None = None
    list_level: NonNegativeInt | None = None
    bold_ratio: Ratio = 0.0
    inline_spans: list[InlineStyleSpan] = Field(default_factory=list)


class NormalizationSpan(StrictModel):
    normalized_start: NonNegativeInt
    normalized_end: PositiveInt
    raw_start: NonNegativeInt
    raw_end: PositiveInt
    kind: NormalizationKind

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.normalized_end <= self.normalized_start:
            raise ValueError("normalized span end must be greater than start")
        if self.raw_end <= self.raw_start:
            raise ValueError("raw span end must be greater than start")
        return self


class NormalizationMap(StrictModel):
    normalization_map_id: Identifier
    source_id: Identifier
    block_id: Identifier
    raw_length: NonNegativeInt
    normalized_length: NonNegativeInt
    spans: list[NormalizationSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.normalized_length == 0:
            if self.spans:
                raise ValueError("empty normalized text cannot have mapping spans")
            return self
        if not self.spans:
            raise ValueError("non-empty normalized text requires mapping spans")

        expected_start = 0
        previous_raw_start = 0
        for span in self.spans:
            if span.normalized_start != expected_start:
                raise ValueError("normalization spans must cover normalized text without gaps")
            if span.raw_start < previous_raw_start or span.raw_end > self.raw_length:
                raise ValueError("normalization spans must be monotonic and inside raw text")
            expected_start = span.normalized_end
            previous_raw_start = span.raw_start
        if expected_start != self.normalized_length:
            raise ValueError("normalization spans do not cover normalized text")
        return self

    def raw_span(self, normalized_start: int, normalized_end: int) -> tuple[int, int]:
        """Map a non-empty normalized code-point span back to raw code points."""

        if not 0 <= normalized_start < normalized_end <= self.normalized_length:
            raise ValueError("normalized span is outside the normalization map")
        overlapping = [
            span
            for span in self.spans
            if span.normalized_end > normalized_start and span.normalized_start < normalized_end
        ]
        if not overlapping:
            raise ValueError("normalized span has no raw mapping")
        mapped_ranges: list[tuple[int, int]] = []
        for span in overlapping:
            overlap_start = max(normalized_start, span.normalized_start)
            overlap_end = min(normalized_end, span.normalized_end)
            normalized_width = span.normalized_end - span.normalized_start
            raw_width = span.raw_end - span.raw_start
            if normalized_width == raw_width:
                mapped_ranges.append(
                    (
                        span.raw_start + overlap_start - span.normalized_start,
                        span.raw_start + overlap_end - span.normalized_start,
                    )
                )
            else:
                mapped_ranges.append((span.raw_start, span.raw_end))
        return min(item[0] for item in mapped_ranges), max(
            item[1] for item in mapped_ranges
        )


class DocumentBlock(RawTextModel):
    block_id: Identifier
    source_id: Identifier
    ordinal: NonNegativeInt
    kind: BlockKind
    raw_text: str
    normalized_text: str
    locator: DocumentLocator
    style: BlockStyle = Field(default_factory=BlockStyle)
    raw_sha256: Sha256Hex
    normalization_map_id: Identifier

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.kind != BlockKind.PAGE_BREAK and not self.raw_text.strip():
            raise ValueError("non-page-break blocks require non-empty raw text")
        digest = sha256(self.raw_text.encode("utf-8")).hexdigest()
        if digest != self.raw_sha256:
            raise ValueError("raw_sha256 does not match raw_text")
        previous_end = 0
        for span in self.style.inline_spans:
            if span.start < previous_end or span.end > len(self.raw_text):
                raise ValueError("inline style spans must be ordered and inside raw_text")
            previous_end = span.end
        return self


class ExtractionWarning(StrictModel):
    code: Identifier
    message: str
    severity: Literal["warning", "info"] = "warning"


class ExtractionQuality(StrictModel):
    status: ExtractionQualityStatus
    page_count: NonNegativeInt | None = None
    empty_page_count: NonNegativeInt = 0
    extracted_char_count: NonNegativeInt = 0
    replacement_character_ratio: Ratio = 0.0
    suspicious_control_ratio: Ratio = 0.0
    duplicate_header_count: NonNegativeInt = 0
    duplicate_footer_count: NonNegativeInt = 0
    overlong_block_count: NonNegativeInt = 0
    warnings: list[ExtractionWarning] = Field(default_factory=list)


class ExtractedDocument(StrictModel):
    source_manifest: SourceManifest
    blocks: list[DocumentBlock]
    normalization_maps: dict[Identifier, NormalizationMap]
    quality: ExtractionQuality

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        expected_ordinals = list(range(len(self.blocks)))
        if [block.ordinal for block in self.blocks] != expected_ordinals:
            raise ValueError("block ordinals must be contiguous and zero-based")
        for block in self.blocks:
            if block.source_id != self.source_manifest.source_id:
                raise ValueError("all blocks must belong to the source manifest")
            normalization_map = self.normalization_maps.get(block.normalization_map_id)
            if normalization_map is None:
                raise ValueError(f"block {block.block_id!r} has no normalization map")
            if normalization_map.block_id != block.block_id:
                raise ValueError("normalization map block_id does not match block")
            if normalization_map.raw_length != len(block.raw_text):
                raise ValueError("normalization map raw length does not match block")
            if normalization_map.normalized_length != len(block.normalized_text):
                raise ValueError("normalization map normalized length does not match block")
        return self
