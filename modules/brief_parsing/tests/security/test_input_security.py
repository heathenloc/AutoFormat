from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from brief_parser.adapters.input_security import FileSecurityValidator, InputSecurityPolicy
from brief_parser.errors import BriefParserError, ErrorCode
from tests.helpers import make_text_pdf


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_rejects_mime_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(make_text_pdf([["Enough synthetic text for extraction."]]))

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
            media_type="text/plain",
        )

    assert error.value.code == ErrorCode.SOURCE_MIME_MISMATCH


def test_rejects_non_utf8_txt(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_TEXT_ENCODING


def test_rejects_docx_path_traversal(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.docx"
    _write_zip(
        path,
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<document/>",
            "../outside.txt": b"unsafe",
        },
    )

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_ARCHIVE_PATH_TRAVERSAL


def test_rejects_docx_dtd(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.docx"
    _write_zip(
        path,
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<!DOCTYPE x [<!ENTITY e 'unsafe'>]><document/>",
        },
    )

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_XML_UNSAFE


def test_rejects_macro_enabled_docx(tmp_path: Path) -> None:
    path = tmp_path / "macro.docx"
    _write_zip(
        path,
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<document/>",
            "word/vbaProject.bin": b"synthetic macro payload",
        },
    )

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_MACRO_ENABLED


def test_rejects_high_compression_ratio_docx(tmp_path: Path) -> None:
    path = tmp_path / "bomb.docx"
    _write_zip(
        path,
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"A" * 1_000_000,
        },
    )

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator(
            InputSecurityPolicy(max_zip_compression_ratio=50)
        ).secure_file(path, source_id="src", client_source_id="brief")

    assert error.value.code == ErrorCode.SOURCE_ARCHIVE_BOMB


def test_direct_text_enforces_character_limit() -> None:
    validator = FileSecurityValidator(InputSecurityPolicy(max_extracted_chars=5))

    with pytest.raises(BriefParserError) as error:
        validator.secure_text(
            "123456",
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_EXTRACTED_TOO_LARGE


def test_rejects_encrypted_pdf(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("synthetic-password")
    buffer = BytesIO()
    writer.write(buffer)
    path.write_bytes(buffer.getvalue())

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator().secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_ENCRYPTED


def test_rejects_pdf_over_page_limit(tmp_path: Path) -> None:
    path = tmp_path / "two-pages.pdf"
    path.write_bytes(make_text_pdf([["Page one text."], ["Page two text."]]))

    with pytest.raises(BriefParserError) as error:
        FileSecurityValidator(InputSecurityPolicy(max_pages=1)).secure_file(
            path,
            source_id="src",
            client_source_id="brief",
        )

    assert error.value.code == ErrorCode.SOURCE_TOO_MANY_PAGES
