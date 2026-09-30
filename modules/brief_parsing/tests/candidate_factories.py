"""Synthetic provider outputs for Phase 3 tests."""

from __future__ import annotations


def candidate_value_payload(*, text: str = "示例值") -> dict[str, object]:
    return {
        "type": "text",
        "text": text,
        "amount": None,
        "range_end": None,
        "unit": None,
        "items": [],
    }


def extractor_output_payload(*, evidence_id: str) -> dict[str, object]:
    return {
        "facts": [
            {
                "candidate_id": "cand_brand",
                "label": "品牌",
                "value": candidate_value_payload(text="示例品牌"),
                "evidence_refs": [evidence_id],
            }
        ],
        "objectives": [],
        "requirements": [],
        "references": [],
        "candidate_conflicts": [],
        "unresolved_items": [],
    }
