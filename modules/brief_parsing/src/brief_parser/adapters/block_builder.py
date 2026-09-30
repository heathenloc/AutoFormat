"""Build stable Document Blocks and normalization maps from parser drafts."""

from __future__ import annotations

from hashlib import sha256

from brief_parser.adapters.normalizer import TextNormalizer
from brief_parser.adapters.parsers.base import BlockDraft
from brief_parser.domain.document import DocumentBlock, NormalizationMap


class BlockBuilder:
    def __init__(self, normalizer: TextNormalizer | None = None) -> None:
        self.normalizer = TextNormalizer() if normalizer is None else normalizer

    def build(
        self,
        *,
        source_id: str,
        drafts: tuple[BlockDraft, ...],
    ) -> tuple[list[DocumentBlock], dict[str, NormalizationMap]]:
        blocks: list[DocumentBlock] = []
        normalization_maps: dict[str, NormalizationMap] = {}
        for ordinal, draft in enumerate(drafts):
            identity = (
                f"{source_id}\x00{ordinal}\x00{draft.kind.value}\x00{draft.raw_text}"
            )
            block_id = f"blk_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
            if draft.kind.value == "page_break":
                normalized_text = ""
                normalization_map = NormalizationMap(
                    normalization_map_id=f"nmap_{sha256(block_id.encode()).hexdigest()[:24]}",
                    source_id=source_id,
                    block_id=block_id,
                    raw_length=len(draft.raw_text),
                    normalized_length=0,
                    spans=[],
                )
            else:
                normalized_text, normalization_map = self.normalizer.normalize(
                    draft.raw_text,
                    source_id=source_id,
                    block_id=block_id,
                )
            block = DocumentBlock(
                block_id=block_id,
                source_id=source_id,
                ordinal=ordinal,
                kind=draft.kind,
                raw_text=draft.raw_text,
                normalized_text=normalized_text,
                locator=draft.locator,
                style=draft.style,
                raw_sha256=sha256(draft.raw_text.encode("utf-8")).hexdigest(),
                normalization_map_id=normalization_map.normalization_map_id,
            )
            blocks.append(block)
            normalization_maps[normalization_map.normalization_map_id] = normalization_map
        return blocks, normalization_maps

