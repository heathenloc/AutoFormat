from hashlib import sha256

import pytest

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.evidence_index import EvidenceIndexBuilder
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.errors import BriefParserError, ErrorCode


def _result():  # type: ignore[no-untyped-def]
    secured = FileSecurityValidator().secure_text(
        "必须  出现品牌名。",
        source_id="src_evidence",
        client_source_id="brief",
    )
    document = DocumentIngestor().ingest(secured)
    segmentation = ClauseSegmenter().segment(document)
    return document, segmentation


def test_evidence_index_uses_exact_raw_code_point_span() -> None:
    document, segmentation = _result()

    evidence = EvidenceIndexBuilder().build(document, segmentation)
    clause = segmentation.clauses[0]
    reference = evidence[clause.evidence_id]

    assert clause.normalized_text == "必须 出现品牌名。"
    assert reference.quote == "必须  出现品牌名。"
    assert reference.start == 0
    assert reference.end == len(reference.quote)
    assert reference.quote_sha256 == sha256(reference.quote.encode("utf-8")).hexdigest()
    assert reference.match_status == "exact"


def test_tampered_clause_cannot_create_evidence() -> None:
    document, segmentation = _result()
    clause = segmentation.clauses[0]
    tampered = segmentation.model_copy(
        update={
            "clauses": [
                clause.model_copy(update={"raw_text": "必须  隐去品牌名。"})
            ]
        }
    )

    with pytest.raises(BriefParserError) as error:
        EvidenceIndexBuilder().build(document, tampered)

    assert error.value.code == ErrorCode.CLAUSE_EVIDENCE_INVALID
