"""Synthetic contract fixtures. Never put customer content here."""

from __future__ import annotations

from hashlib import sha256


def requirement_ir_payload() -> dict[str, object]:
    quote = "成片时长不得超过60秒"
    evidence_id = "ev_duration"
    return {
        "artifact_id": "art_sample",
        "artifact_version": 1,
        "request_id": "req_sample",
        "created_at": "2026-09-20T10:00:00Z",
        "readiness": "complete",
        "locale": "zh-CN",
        "domain_pack": {"id": "advertising_brief", "version": "1.0.0"},
        "pipeline": {
            "version": "1.0.0",
            "parser_versions": {"text": "1.0.0"},
            "prompt_versions": {},
            "model_configs": {"provider": "fake"},
        },
        "source_manifest": [
            {
                "source_id": "src_sample",
                "client_source_id": "brief",
                "kind": "text",
                "filename": None,
                "media_type": "text/plain",
                "byte_size": len(quote.encode("utf-8")),
                "sha256": sha256(quote.encode("utf-8")).hexdigest(),
                "language_hints": ["zh-CN"],
                "parser_id": "direct-text",
                "parser_version": "1.0.0",
                "extraction_status": "complete",
                "warnings": [],
            }
        ],
        "facts": [],
        "objectives": [],
        "requirements": [
            {
                "id": "req_duration",
                "semantic_key": "duration.primary_video.maximum",
                "category": "duration",
                "custom_category": None,
                "label": "主视频时长上限",
                "subject": "primary_video",
                "modality": "must",
                "operator": "lte",
                "value": {"type": "duration", "amount": 60, "unit": "second"},
                "scope": {"applies_to": ["primary_video"], "excludes": []},
                "condition": None,
                "priority": "critical",
                "machine_checkability": "text_checkable",
                "verification_status": "verified",
                "verification_basis": ["evidence_exact_match", "numeric_rule_match"],
                "evidence_refs": [evidence_id],
                "origin": "source",
                "downstream_policy": "enforce",
            }
        ],
        "references": [],
        "conflicts": [],
        "unresolved_items": [],
        "unclassified_content": [],
        "evidence_index": {
            evidence_id: {
                "evidence_id": evidence_id,
                "source_id": "src_sample",
                "block_id": "blk_sample",
                "start": 0,
                "end": len(quote),
                "index_basis": "unicode_code_point",
                "quote": quote,
                "quote_sha256": sha256(quote.encode("utf-8")).hexdigest(),
                "locator": {
                    "page": None,
                    "paragraph": 0,
                    "table": None,
                    "section_path": ["交付要求"],
                },
                "match_status": "exact",
            }
        },
        "quality": {
            "source_extraction_quality": {"src_sample": "complete"},
            "clause_count": 1,
            "classified_clause_count": 1,
            "unclassified_clause_count": 0,
            "coverage_ratio": 1.0,
            "evidence_validity_ratio": 1.0,
            "numeric_validation_ratio": 1.0,
            "conflict_count": 0,
            "unresolved_count": 0,
            "blocker_count": 0,
            "provider_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "readiness_reason_codes": [],
        },
        "extensions": [],
    }

