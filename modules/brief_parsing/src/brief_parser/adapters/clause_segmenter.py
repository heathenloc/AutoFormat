"""Deterministic clause segmentation over normalized document blocks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from unicodedata import east_asian_width

from brief_parser.domain.document import BlockKind, DocumentBlock, ExtractedDocument
from brief_parser.domain.foundation import Clause, ClauseChunk, ClauseSegmentation
from brief_parser.errors import BriefParserError, ErrorCode


@dataclass(frozen=True, slots=True)
class _ClauseDraft:
    clause_id: str
    evidence_id: str
    block: DocumentBlock
    ordinal: int
    normalized_start: int
    normalized_end: int
    raw_start: int
    raw_end: int
    normalized_text: str
    raw_text: str
    estimated_tokens: int


class ClauseSegmenter:
    """Split complete source clauses without losing raw-text provenance."""

    _CONTENT_KINDS = frozenset(
        {
            BlockKind.HEADING,
            BlockKind.PARAGRAPH,
            BlockKind.LIST_ITEM,
            BlockKind.TABLE_CELL,
            BlockKind.FOOTNOTE,
        }
    )
    _STRONG_BOUNDARIES = frozenset("。\uff01\uff1f!?\uff1b;")
    _CLOSING_PUNCTUATION = frozenset(
        "\u201d\u2019\"\u300d\u300f\u300b\u3011\uff09)]"
    )

    def __init__(
        self,
        *,
        long_block_chars: int = 500,
        target_chunk_tokens: int = 8_000,
        hard_chunk_tokens: int = 12_000,
    ) -> None:
        if long_block_chars <= 0:
            raise ValueError("long_block_chars must be positive")
        if target_chunk_tokens <= 0:
            raise ValueError("target_chunk_tokens must be positive")
        if hard_chunk_tokens < target_chunk_tokens:
            raise ValueError("hard_chunk_tokens must be at least target_chunk_tokens")
        self._long_block_chars = long_block_chars
        self._target_chunk_tokens = target_chunk_tokens
        self._hard_chunk_tokens = hard_chunk_tokens

    def segment(self, document: ExtractedDocument) -> ClauseSegmentation:
        drafts: list[_ClauseDraft] = []
        for block in document.blocks:
            if block.kind not in self._CONTENT_KINDS or not block.normalized_text.strip():
                continue
            normalization_map = document.normalization_maps[block.normalization_map_id]
            for normalized_start, normalized_end in self._ranges(block.normalized_text):
                raw_start, raw_end = normalization_map.raw_span(
                    normalized_start,
                    normalized_end,
                )
                normalized_text = block.normalized_text[normalized_start:normalized_end]
                raw_text = block.raw_text[raw_start:raw_end]
                identity = (
                    f"{block.source_id}\x00{block.block_id}\x00{normalized_start}\x00"
                    f"{normalized_end}\x00{normalized_text}"
                )
                clause_id = f"cl_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
                estimated_tokens = self._estimate_tokens(normalized_text)
                if estimated_tokens > self._hard_chunk_tokens:
                    raise BriefParserError(
                        ErrorCode.CLAUSE_TOO_LARGE,
                        "存在无法在完整 Clause 边界内安全分块的超长内容。",
                        source_id=block.source_id,
                        details={"block_id": block.block_id},
                    )
                drafts.append(
                    _ClauseDraft(
                        clause_id=clause_id,
                        evidence_id=(
                            f"ev_{sha256(('evidence\x00' + clause_id).encode()).hexdigest()[:24]}"
                        ),
                        block=block,
                        ordinal=len(drafts),
                        normalized_start=normalized_start,
                        normalized_end=normalized_end,
                        raw_start=raw_start,
                        raw_end=raw_end,
                        normalized_text=normalized_text,
                        raw_text=raw_text,
                        estimated_tokens=estimated_tokens,
                    )
                )

        grouped = self._group_chunks(drafts)
        chunks: list[ClauseChunk] = []
        chunk_by_clause: dict[str, str] = {}
        for ordinal, group in enumerate(grouped):
            clause_ids = [draft.clause_id for draft in group]
            fingerprint = f"{ordinal}\x00" + "\x00".join(clause_ids)
            chunk_id = f"chk_{sha256(fingerprint.encode()).hexdigest()[:24]}"
            chunks.append(
                ClauseChunk(
                    chunk_id=chunk_id,
                    ordinal=ordinal,
                    clause_ids=clause_ids,
                    estimated_input_tokens=sum(item.estimated_tokens for item in group),
                )
            )
            chunk_by_clause.update(dict.fromkeys(clause_ids, chunk_id))

        clauses = [
            Clause(
                clause_id=draft.clause_id,
                source_id=draft.block.source_id,
                block_id=draft.block.block_id,
                ordinal=draft.ordinal,
                block_kind=draft.block.kind,
                normalized_start=draft.normalized_start,
                normalized_end=draft.normalized_end,
                raw_start=draft.raw_start,
                raw_end=draft.raw_end,
                normalized_text=draft.normalized_text,
                raw_text=draft.raw_text,
                evidence_id=draft.evidence_id,
                primary_chunk_id=chunk_by_clause[draft.clause_id],
                locator=draft.block.locator,
            )
            for draft in drafts
        ]
        return ClauseSegmentation(clauses=clauses, chunks=chunks)

    def _ranges(self, text: str) -> list[tuple[int, int]]:
        whole = self._trim(text, 0, len(text))
        if whole is None:
            return []
        long_block = len(text) > self._long_block_chars
        if not long_block and not any(
            char in self._STRONG_BOUNDARIES for char in text
        ):
            return [whole]

        ranges: list[tuple[int, int]] = []
        start = 0
        for index, char in enumerate(text):
            if index < start:
                continue
            is_period_boundary = (
                long_block
                and char == "."
                and (index + 1 == len(text) or text[index + 1].isspace())
                and (index == 0 or not text[index - 1].isdigit())
            )
            if char not in self._STRONG_BOUNDARIES and not is_period_boundary:
                continue
            end = index + 1
            while end < len(text) and text[end] in self._CLOSING_PUNCTUATION:
                end += 1
            trimmed = self._trim(text, start, end)
            if trimmed is not None:
                ranges.append(trimmed)
            start = end
        trailing = self._trim(text, start, len(text))
        if trailing is not None:
            ranges.append(trailing)
        return ranges or [whole]

    @staticmethod
    def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return None if start == end else (start, end)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        wide = sum(east_asian_width(char) in {"W", "F"} for char in text)
        narrow = len(text) - wide
        return max(1, wide + ceil(narrow / 4))

    def _group_chunks(self, drafts: list[_ClauseDraft]) -> list[list[_ClauseDraft]]:
        groups: list[list[_ClauseDraft]] = []
        current: list[_ClauseDraft] = []
        current_tokens = 0
        for draft in drafts:
            projected = current_tokens + draft.estimated_tokens
            if current and projected > self._target_chunk_tokens:
                groups.append(current)
                current = []
                current_tokens = 0
            if current_tokens + draft.estimated_tokens > self._hard_chunk_tokens:
                groups.append(current)
                current = []
                current_tokens = 0
            current.append(draft)
            current_tokens += draft.estimated_tokens
        if current:
            groups.append(current)
        return groups
