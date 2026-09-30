from brief_parser.adapters.normalizer import TextNormalizer


def test_normalizer_preserves_raw_code_point_mapping() -> None:
    raw = "Cafe\u0301\r\n  60秒"

    normalized, mapping = TextNormalizer().normalize(
        raw,
        source_id="src_sample",
        block_id="blk_sample",
    )

    assert normalized == "Café 60秒"
    assert mapping.raw_span(1, 3) == (1, 3)
    assert mapping.raw_span(3, 4) == (3, 5)
    assert mapping.raw_span(4, 5) == (5, 9)
    assert mapping.raw_span(5, len(normalized)) == (9, len(raw))


def test_normalization_is_deterministic() -> None:
    normalizer = TextNormalizer()

    first = normalizer.normalize("必须  出现", source_id="src", block_id="blk")
    second = normalizer.normalize("必须  出现", source_id="src", block_id="blk")

    assert first == second
