import pytest

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.evidence_index import EvidenceIndexBuilder
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.errors import BriefParserError, ErrorCode


def _document(text: str):  # type: ignore[no-untyped-def]
    secured = FileSecurityValidator().secure_text(
        text,
        source_id="src_clause",
        client_source_id="brief",
    )
    return DocumentIngestor().ingest(secured)


def test_long_blocks_split_only_at_complete_sentence_boundaries() -> None:
    document = _document("# 交付要求\n如果投放抖音，则必须竖屏。否则需提供横版。")
    segmenter = ClauseSegmenter(long_block_chars=12)

    result = segmenter.segment(document)

    assert [clause.normalized_text for clause in result.clauses] == [
        "# 交付要求",
        "如果投放抖音，则必须竖屏。",
        "否则需提供横版。",
    ]
    assert result.clauses[1].raw_text == "如果投放抖音，则必须竖屏。"
    assert {clause.primary_chunk_id for clause in result.clauses} <= {
        chunk.chunk_id for chunk in result.chunks
    }


def test_short_chinese_sentences_have_separate_exact_evidence() -> None:
    document = _document("品牌为青禾。成片时长不得超过60秒。")
    segmentation = ClauseSegmenter().segment(document)
    evidence = EvidenceIndexBuilder().build(document, segmentation)

    assert [clause.raw_text for clause in segmentation.clauses] == [
        "品牌为青禾。",
        "成片时长不得超过60秒。",
    ]
    assert len(segmentation.chunks) == 1
    for clause in segmentation.clauses:
        cited = evidence[clause.evidence_id]
        block = next(item for item in document.blocks if item.block_id == clause.block_id)
        assert block.raw_text[cited.start : cited.end] == cited.quote == clause.raw_text


def test_short_sentence_keeps_closing_quote_with_its_evidence() -> None:
    document = _document("开场说“你好。”结尾必须说购买。")

    clauses = ClauseSegmenter().segment(document).clauses

    assert [clause.raw_text for clause in clauses] == [
        "开场说“你好。”",
        "结尾必须说购买。",
    ]


def test_segmentation_and_chunk_ids_are_stable() -> None:
    document = _document("必须出现品牌名。\n时长不得超过60秒。")
    segmenter = ClauseSegmenter(target_chunk_tokens=8, hard_chunk_tokens=20)

    first = segmenter.segment(document)
    second = segmenter.segment(document)

    assert first == second
    assert len(first.chunks) == 2
    assert sorted(
        clause_id for chunk in first.chunks for clause_id in chunk.clause_ids
    ) == sorted(clause.clause_id for clause in first.clauses)


def test_single_clause_over_hard_chunk_limit_is_rejected() -> None:
    document = _document("必须完整保留这条不可截断的要求。")

    with pytest.raises(BriefParserError) as error:
        ClauseSegmenter(
            long_block_chars=1_000,
            target_chunk_tokens=2,
            hard_chunk_tokens=3,
        ).segment(document)

    assert error.value.code == ErrorCode.CLAUSE_TOO_LARGE
