from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from brief_parser.domain.requirement_ir import EvidenceReference, RequirementIR
from tests.factories import requirement_ir_payload


def test_requirement_ir_round_trip() -> None:
    model = RequirementIR.model_validate(requirement_ir_payload())

    restored = RequirementIR.model_validate_json(model.model_dump_json())

    assert restored == model
    assert model.schema_version == "requirement-ir/1.0"


def test_requirement_ir_rejects_unknown_evidence() -> None:
    payload = requirement_ir_payload()
    requirements = payload["requirements"]
    assert isinstance(requirements, list)
    requirements[0]["evidence_refs"] = ["ev_missing"]

    with pytest.raises(ValidationError, match="unknown evidence"):
        RequirementIR.model_validate(payload)


def test_requirement_ir_rejects_unknown_fields() -> None:
    payload = requirement_ir_payload()
    payload["confidence"] = 0.99

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RequirementIR.model_validate(payload)


def test_evidence_hash_is_verified() -> None:
    payload = deepcopy(requirement_ir_payload())
    evidence_index = payload["evidence_index"]
    assert isinstance(evidence_index, dict)
    evidence_index["ev_duration"]["quote_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="quote_sha256 does not match quote"):
        RequirementIR.model_validate(payload)


def test_evidence_quote_preserves_boundary_whitespace() -> None:
    quote = " exact evidence "

    evidence = EvidenceReference.model_validate(
        {
            "evidence_id": "ev_whitespace",
            "source_id": "src_sample",
            "block_id": "blk_sample",
            "start": 2,
            "end": 18,
            "quote": quote,
            "quote_sha256": sha256(quote.encode("utf-8")).hexdigest(),
            "locator": {"page": 1},
            "match_status": "exact",
        }
    )

    assert evidence.quote == quote
