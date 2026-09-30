"""Coverage ledger construction with one auditable entry per clause."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from brief_parser.domain.foundation import (
    ClauseSegmentation,
    CoverageClassification,
    CoverageLedger,
    CoverageLedgerEntry,
    EvidenceIndex,
)


class CoverageLedgerBuilder:
    def build(
        self,
        segmentation: ClauseSegmentation,
        evidence_index: EvidenceIndex,
        *,
        classifications: Mapping[str, CoverageClassification] | None = None,
        reason_codes: Mapping[str, Sequence[str]] | None = None,
    ) -> CoverageLedger:
        classifications = {} if classifications is None else classifications
        reason_codes = {} if reason_codes is None else reason_codes
        clause_ids = {clause.clause_id for clause in segmentation.clauses}
        unknown = (set(classifications) | set(reason_codes)) - clause_ids
        if unknown:
            raise ValueError(f"coverage metadata references unknown clauses: {sorted(unknown)}")

        entries: list[CoverageLedgerEntry] = []
        for clause in segmentation.clauses:
            if clause.evidence_id not in evidence_index:
                raise ValueError(f"clause {clause.clause_id!r} has no evidence")
            classification = classifications.get(
                clause.clause_id,
                CoverageClassification.UNCLASSIFIED,
            )
            reasons = list(reason_codes.get(clause.clause_id, ()))
            if classification == CoverageClassification.UNCLASSIFIED and not reasons:
                reasons = ["not_classified"]
            entries.append(
                CoverageLedgerEntry(
                    clause_id=clause.clause_id,
                    classification=classification,
                    evidence_refs=[clause.evidence_id],
                    reason_codes=reasons,
                )
            )

        classified_count = sum(
            entry.classification != CoverageClassification.UNCLASSIFIED
            for entry in entries
        )
        clause_count = len(entries)
        return CoverageLedger(
            entries=entries,
            clause_count=clause_count,
            classified_clause_count=classified_count,
            unclassified_clause_count=clause_count - classified_count,
            coverage_ratio=classified_count / clause_count if clause_count else 0.0,
        )
