from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.domain.document import BlockKind


def test_direct_text_produces_typed_blocks_and_maps() -> None:
    source = FileSecurityValidator().secure_text(
        "# 交付要求\r\n- 成片不得超过 60 秒\f下一页继续说明",
        source_id="src_text",
        client_source_id="brief",
        language_hints=("zh-CN",),
    )

    result = DocumentIngestor().ingest(source)

    assert [block.kind for block in result.blocks] == [
        BlockKind.HEADING,
        BlockKind.LIST_ITEM,
        BlockKind.PAGE_BREAK,
        BlockKind.PARAGRAPH,
    ]
    assert result.blocks[0].locator.section_path == ["交付要求"]
    assert result.blocks[1].locator.page == 1
    assert result.blocks[3].locator.page == 2
    assert result.quality.page_count == 2
    assert result.source_manifest.extraction_status == "complete"
    assert len(result.normalization_maps) == len(result.blocks)


def test_same_text_produces_stable_block_ids() -> None:
    validator = FileSecurityValidator()
    ingestor = DocumentIngestor()
    source = validator.secure_text(
        "必须出现品牌名。",
        source_id="src_text",
        client_source_id="brief",
    )

    first = ingestor.ingest(source)
    second = ingestor.ingest(source)

    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]

