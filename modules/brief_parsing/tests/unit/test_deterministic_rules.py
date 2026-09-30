from decimal import Decimal

from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.domain.enums import Modality, Operator
from brief_parser.domain.foundation import NumericKind
from brief_parser.validators.deterministic_rules import DeterministicRuleAnalyzer


def _analyses(text: str):  # type: ignore[no-untyped-def]
    secured = FileSecurityValidator().secure_text(
        text,
        source_id="src_rules",
        client_source_id="brief",
    )
    document = DocumentIngestor().ingest(secured)
    segmentation = ClauseSegmenter().segment(document)
    return DeterministicRuleAnalyzer().analyze(document, segmentation)


def _analyze(text: str):  # type: ignore[no-untyped-def]
    return _analyses(text)[0]


def test_numbers_dates_units_and_operators_are_extracted_without_model() -> None:
    analysis = _analyze(
        "成片时长不得超过60秒，预算为¥1,200.50，折扣不低于10%，截止日期为2026年9月30日。"
    )

    assert [item.amount for item in analysis.numeric_mentions] == [
        Decimal("60"),
        Decimal("1200.50"),
        Decimal("10"),
    ]
    assert [item.unit for item in analysis.numeric_mentions] == [
        "second",
        "cny",
        "percent",
    ]
    assert analysis.numeric_mentions[0].operator == Operator.LTE
    assert analysis.numeric_mentions[1].kind == NumericKind.CURRENCY
    assert analysis.numeric_mentions[2].operator == Operator.GTE
    assert analysis.date_mentions[0].value.isoformat() == "2026-09-30"
    assert analysis.date_mentions[0].operator == Operator.BEFORE
    assert analysis.modality_mentions[0].modality == Modality.MUST


def test_chinese_number_and_range_rules_are_deterministic() -> None:
    analysis = _analyze("时长至少六十秒，可在15至30秒之间调整。")

    assert analysis.numeric_mentions[0].amount == Decimal("60")
    assert analysis.numeric_mentions[0].operator == Operator.GTE
    assert analysis.numeric_mentions[1].kind == NumericKind.RANGE
    assert analysis.numeric_mentions[1].amount == Decimal("15")
    assert analysis.numeric_mentions[1].range_end == Decimal("30")
    assert analysis.numeric_mentions[1].operator == Operator.BETWEEN


def test_prohibition_preference_and_permission_modalities_do_not_overlap() -> None:
    analyses = _analyses("禁止出现竞品名称\uff1b建议使用轻松语气\uff1b可以加入字幕。")

    assert [
        item.modality
        for analysis in analyses
        for item in analysis.modality_mentions
    ] == [
        Modality.MUST_NOT,
        Modality.SHOULD,
        Modality.MAY,
    ]


def test_invalid_calendar_date_is_not_accepted() -> None:
    analysis = _analyze("截止日期为2026年2月30日。")

    assert analysis.date_mentions == []
