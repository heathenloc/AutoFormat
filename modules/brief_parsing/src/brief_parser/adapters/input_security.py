"""Deterministic pre-model input validation and file security checks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource, SourceKind

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
TEXT_MEDIA_TYPE = "text/plain"
MEDIA_TYPES: dict[SourceKind, str] = {
    "text": TEXT_MEDIA_TYPE,
    "txt": TEXT_MEDIA_TYPE,
    "docx": DOCX_MEDIA_TYPE,
    "pdf": PDF_MEDIA_TYPE,
}


@dataclass(frozen=True, slots=True)
class InputSecurityPolicy:
    max_file_bytes: int = 20 * 1024 * 1024
    max_pages: int = 100
    max_extracted_chars: int = 250_000
    max_docx_entries: int = 10_000
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    max_zip_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        numeric_values = (
            self.max_file_bytes,
            self.max_pages,
            self.max_extracted_chars,
            self.max_docx_entries,
            self.max_docx_uncompressed_bytes,
        )
        if any(value <= 0 for value in numeric_values):
            raise ValueError("all input security limits must be positive")
        if self.max_zip_compression_ratio <= 1:
            raise ValueError("max_zip_compression_ratio must be greater than one")


class FileSecurityValidator:
    """Load a source only after its type, size, and container safety are verified."""

    def __init__(self, policy: InputSecurityPolicy | None = None) -> None:
        self.policy = InputSecurityPolicy() if policy is None else policy

    def secure_text(
        self,
        text: str,
        *,
        source_id: str,
        client_source_id: str,
        language_hints: tuple[str, ...] = (),
    ) -> SecuredSource:
        if not text.strip():
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "文本输入不能为空。")
        if "\x00" in text:
            raise BriefParserError(
                ErrorCode.SOURCE_TEXT_ENCODING,
                "文本包含 NUL 字符，无法作为安全文本处理。",
            )
        if len(text) > self.policy.max_extracted_chars:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTED_TOO_LARGE,
                "文本字符数超过允许上限。",
                details={"max_extracted_chars": self.policy.max_extracted_chars},
            )
        content = text.encode("utf-8")
        self._validate_byte_size(len(content))
        return SecuredSource(
            source_id=source_id,
            client_source_id=client_source_id,
            kind="text",
            filename=None,
            media_type=TEXT_MEDIA_TYPE,
            content=content,
            byte_size=len(content),
            sha256=sha256(content).hexdigest(),
            language_hints=language_hints,
        )

    def secure_file(
        self,
        path: Path,
        *,
        source_id: str,
        client_source_id: str,
        media_type: str | None = None,
        language_hints: tuple[str, ...] = (),
    ) -> SecuredSource:
        if path.is_symlink():
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "不接受符号链接输入，请提供实际文件。",
            )
        if not path.is_file():
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "输入文件不存在或不是普通文件。")

        byte_size = path.stat().st_size
        self._validate_byte_size(byte_size)
        content = path.read_bytes()
        if len(content) != byte_size:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTION_FAILED,
                "读取文件时检测到大小变化，请重试。",
                retryable=True,
            )

        suffix = path.suffix.lower()
        kind = self._detect_kind(content, suffix=suffix)
        expected_media_type = MEDIA_TYPES[kind]
        if media_type is not None:
            supplied = media_type.partition(";")[0].strip().lower()
            if supplied != expected_media_type:
                raise BriefParserError(
                    ErrorCode.SOURCE_MIME_MISMATCH,
                    "声明的媒体类型与文件内容不一致。",
                    details={"expected_media_type": expected_media_type},
                )

        warnings: tuple[str, ...] = ()
        page_count: int | None = None
        if kind == "txt":
            self._validate_text(content)
        elif kind == "docx":
            warnings = self._validate_docx(content)
        elif kind == "pdf":
            page_count = self._validate_pdf(content)

        return SecuredSource(
            source_id=source_id,
            client_source_id=client_source_id,
            kind=kind,
            filename=path.name,
            media_type=expected_media_type,
            content=content,
            byte_size=byte_size,
            sha256=sha256(content).hexdigest(),
            language_hints=language_hints,
            page_count=page_count,
            security_warnings=warnings,
        )

    def _validate_byte_size(self, byte_size: int) -> None:
        if byte_size <= 0:
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "输入文件不能为空。")
        if byte_size > self.policy.max_file_bytes:
            raise BriefParserError(
                ErrorCode.SOURCE_TOO_LARGE,
                "输入文件超过允许的大小上限。",
                details={"max_file_bytes": self.policy.max_file_bytes},
            )

    def _detect_kind(self, content: bytes, *, suffix: str) -> SourceKind:
        if content.startswith(b"%PDF-"):
            if suffix != ".pdf":
                raise BriefParserError(
                    ErrorCode.SOURCE_MIME_MISMATCH,
                    "PDF 内容必须使用 .pdf 扩展名。",
                )
            return "pdf"
        if content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            if suffix != ".docx":
                raise BriefParserError(
                    ErrorCode.SOURCE_MIME_MISMATCH,
                    "DOCX 内容必须使用 .docx 扩展名。",
                )
            return "docx"
        if suffix == ".txt":
            return "txt"
        if suffix in {".doc", ".docm"}:
            raise BriefParserError(
                ErrorCode.SOURCE_UNSUPPORTED,
                "不支持 .doc 或启用宏的 Word 文件，请提供 .docx。",
            )
        raise BriefParserError(
            ErrorCode.SOURCE_UNSUPPORTED,
            "仅支持 UTF-8 TXT、DOCX 和具有文本层的 PDF。",
        )

    def _validate_text(self, content: bytes) -> None:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BriefParserError(
                ErrorCode.SOURCE_TEXT_ENCODING,
                "TXT 文件必须使用 UTF-8 编码。",
            ) from exc
        if not text.strip():
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "TXT 文件没有可解析文本。")
        if "\x00" in text:
            raise BriefParserError(
                ErrorCode.SOURCE_TEXT_ENCODING,
                "TXT 文件包含 NUL 字符，疑似二进制内容。",
            )
        if len(text) > self.policy.max_extracted_chars:
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTED_TOO_LARGE,
                "TXT 提取后的字符数超过允许上限。",
                details={"max_extracted_chars": self.policy.max_extracted_chars},
            )

    def _validate_docx(self, content: bytes) -> tuple[str, ...]:
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > self.policy.max_docx_entries:
                    self._raise_zip_bomb()
                names = {entry.filename for entry in entries}
                required = {"[Content_Types].xml", "word/document.xml"}
                if not required.issubset(names):
                    raise BriefParserError(
                        ErrorCode.SOURCE_ARCHIVE_INVALID,
                        "文件不是有效的 DOCX 文档。",
                    )

                total_uncompressed = 0
                for entry in entries:
                    self._validate_zip_entry(entry)
                    total_uncompressed += entry.file_size
                    if total_uncompressed > self.policy.max_docx_uncompressed_bytes:
                        self._raise_zip_bomb()

                bad_entry = archive.testzip()
                if bad_entry is not None:
                    raise BriefParserError(
                        ErrorCode.SOURCE_ARCHIVE_INVALID,
                        "DOCX 压缩包校验失败。",
                    )

                lowered_names = {name.lower() for name in names}
                if "word/vbaproject.bin" in lowered_names:
                    raise BriefParserError(
                        ErrorCode.SOURCE_MACRO_ENABLED,
                        "不接受包含 VBA 宏的 Word 文件。",
                    )

                content_types = archive.read("[Content_Types].xml")
                lowered_content_types = content_types.lower()
                if b"macroenabled" in lowered_content_types:
                    raise BriefParserError(
                        ErrorCode.SOURCE_MACRO_ENABLED,
                        "不接受启用宏的 Word 内容类型。",
                    )

                for entry in entries:
                    lowered = entry.filename.lower()
                    if lowered.endswith((".xml", ".rels")):
                        xml = archive.read(entry)
                        lowered_xml = xml.lower()
                        if b"<!doctype" in lowered_xml or b"<!entity" in lowered_xml:
                            raise BriefParserError(
                                ErrorCode.SOURCE_XML_UNSAFE,
                                "DOCX 包含不允许的 DTD 或实体声明。",
                            )

                warnings: list[str] = []
                if any(name.startswith("word/embeddings/") for name in lowered_names):
                    warnings.append("DOCX_EMBEDDED_OBJECT_IGNORED")
                relationship_name = "word/_rels/document.xml.rels"
                if relationship_name in names:
                    relationships = archive.read(relationship_name).lower()
                    if b'targetmode="external"' in relationships:
                        warnings.append("DOCX_EXTERNAL_RELATIONSHIP_IGNORED")
                return tuple(warnings)
        except BriefParserError:
            raise
        except (BadZipFile, KeyError, RuntimeError, OSError) as exc:
            raise BriefParserError(
                ErrorCode.SOURCE_ARCHIVE_INVALID,
                "DOCX 压缩包损坏或无法安全读取。",
            ) from exc

    def _validate_zip_entry(self, entry: ZipInfo) -> None:
        name = entry.filename
        path = PurePosixPath(name)
        if (
            "\\" in name
            or path.is_absolute()
            or ".." in path.parts
            or any(":" in part for part in path.parts)
        ):
            raise BriefParserError(
                ErrorCode.SOURCE_ARCHIVE_PATH_TRAVERSAL,
                "DOCX 压缩包包含不安全路径。",
            )
        if entry.flag_bits & 0x1:
            raise BriefParserError(
                ErrorCode.SOURCE_ENCRYPTED,
                "不接受包含加密条目的 DOCX。",
            )
        if entry.is_dir() or entry.file_size == 0:
            return
        compression_ratio = entry.file_size / max(entry.compress_size, 1)
        if compression_ratio > self.policy.max_zip_compression_ratio:
            self._raise_zip_bomb()

    def _raise_zip_bomb(self) -> None:
        raise BriefParserError(
            ErrorCode.SOURCE_ARCHIVE_BOMB,
            "DOCX 解压规模或压缩比超过安全上限。",
        )

    def _validate_pdf(self, content: bytes) -> int:
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise BriefParserError(
                    ErrorCode.SOURCE_ENCRYPTED,
                    "不接受密码保护或加密的 PDF。",
                )
            page_count = len(reader.pages)
        except BriefParserError:
            raise
        except (PdfReadError, ValueError, OSError) as exc:
            raise BriefParserError(
                ErrorCode.SOURCE_PDF_INVALID,
                "PDF 损坏或无法安全解析。",
            ) from exc
        if page_count == 0:
            raise BriefParserError(ErrorCode.SOURCE_PDF_INVALID, "PDF 不包含页面。")
        if page_count > self.policy.max_pages:
            raise BriefParserError(
                ErrorCode.SOURCE_TOO_MANY_PAGES,
                "PDF 页数超过允许上限。",
                details={"max_pages": self.policy.max_pages},
            )
        return page_count

