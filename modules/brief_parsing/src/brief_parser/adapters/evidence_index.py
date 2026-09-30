"""Build and validate exact evidence references for deterministic clauses."""

from __future__ import annotations

from hashlib import sha256

from brief_parser.domain.document import ExtractedDocument
from brief_parser.domain.enums import EvidenceMatchStatus
from brief_parser.domain.foundation import ClauseSegmentation, EvidenceIndex
from brief_parser.domain.requirement_ir import EvidenceReference, SourceLocator
from brief_parser.errors import BriefParserError, ErrorCode


class EvidenceIndexBuilder:
    def build(
        self,
        document: ExtractedDocument,
        segmentation: ClauseSegmentation,
    ) -> EvidenceIndex:
        blocks = {block.block_id: block for block in document.blocks}
        evidence_index: EvidenceIndex = {}
        for clause in segmentation.clauses:
            block = blocks.get(clause.block_id)
            if block is None or clause.source_id != document.source_manifest.source_id:
                self._invalid(clause.source_id, clause.block_id)
            assert block is not None
            normalization_map = document.normalization_maps.get(block.normalization_map_id)
            if normalization_map is None:
                self._invalid(clause.source_id, clause.block_id)
            assert normalization_map is not None
            expected_raw_span = normalization_map.raw_span(
                clause.normalized_start,
                clause.normalized_end,
            )
            if (
                block.normalized_text[clause.normalized_start : clause.normalized_end]
                != clause.normalized_text
                or expected_raw_span != (clause.raw_start, clause.raw_end)
                or block.raw_text[clause.raw_start : clause.raw_end] != clause.raw_text
            ):
                self._invalid(clause.source_id, clause.block_id)

            if clause.evidence_id in evidence_index:
                self._invalid(clause.source_id, clause.block_id)
            evidence_index[clause.evidence_id] = EvidenceReference(
                evidence_id=clause.evidence_id,
                source_id=clause.source_id,
                block_id=clause.block_id,
                start=clause.raw_start,
                end=clause.raw_end,
                quote=clause.raw_text,
                quote_sha256=sha256(clause.raw_text.encode("utf-8")).hexdigest(),
                locator=SourceLocator(
                    page=clause.locator.page,
                    paragraph=clause.locator.paragraph,
                    table=clause.locator.table,
                    section_path=clause.locator.section_path,
                ),
                match_status=EvidenceMatchStatus.EXACT,
            )
        return evidence_index

    @staticmethod
    def _invalid(source_id: str, block_id: str) -> None:
        raise BriefParserError(
            ErrorCode.CLAUSE_EVIDENCE_INVALID,
            "Clause 无法精确映射回原文 Evidence。",
            source_id=source_id,
            details={"block_id": block_id},
        )
