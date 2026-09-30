from pathlib import Path

import pytest
from pypdf import PdfWriter

from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.domain.document import BlockKind
from brief_parser.errors import BriefParserError, ErrorCode
from tests.helpers import make_text_pdf


def test_pdf_preserves_pages_and_deduplicates_margins(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(
        make_text_pdf(
            [
                ["Campaign Brief", "First page requirement has enough text.", "Confidential"],
                ["Campaign Brief", "Second page requirement has enough text.", "Confidential"],
                ["Campaign Brief", "Third page requirement has enough text.", "Confidential"],
            ]
        )
    )
    source = FileSecurityValidator().secure_file(
        path,
        source_id="src_pdf",
        client_source_id="brief",
    )

    result = DocumentIngestor().ingest(source)

    assert sum(block.kind == BlockKind.HEADER for block in result.blocks) == 1
    assert sum(block.kind == BlockKind.FOOTER for block in result.blocks) == 1
    assert result.quality.duplicate_header_count == 2
    assert result.quality.duplicate_footer_count == 2
    assert result.quality.page_count == 3
    assert result.source_manifest.extraction_status == "complete"
    assert result.quality.status == "warning"
    assert "DUPLICATE_HEADERS_REMOVED" in result.source_manifest.warnings
    assert any(block.locator.page == 3 for block in result.blocks)


def test_blank_pdf_is_rejected_before_model_use(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)
    source = FileSecurityValidator().secure_file(
        path,
        source_id="src_pdf",
        client_source_id="brief",
    )

    with pytest.raises(BriefParserError) as error:
        DocumentIngestor().ingest(source)

    assert error.value.code == ErrorCode.SOURCE_SCANNED_PDF
