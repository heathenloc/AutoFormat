"""Safe, version-neutral application error definitions."""

from enum import StrEnum
from typing import Any

from brief_parser.domain.base import Identifier, StrictModel


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_TOO_MANY_PAGES = "SOURCE_TOO_MANY_PAGES"
    SOURCE_EXTRACTED_TOO_LARGE = "SOURCE_EXTRACTED_TOO_LARGE"
    SOURCE_MIME_MISMATCH = "SOURCE_MIME_MISMATCH"
    SOURCE_TEXT_ENCODING = "SOURCE_TEXT_ENCODING"
    SOURCE_ARCHIVE_INVALID = "SOURCE_ARCHIVE_INVALID"
    SOURCE_ARCHIVE_PATH_TRAVERSAL = "SOURCE_ARCHIVE_PATH_TRAVERSAL"
    SOURCE_ARCHIVE_BOMB = "SOURCE_ARCHIVE_BOMB"
    SOURCE_XML_UNSAFE = "SOURCE_XML_UNSAFE"
    SOURCE_MACRO_ENABLED = "SOURCE_MACRO_ENABLED"
    SOURCE_ENCRYPTED = "SOURCE_ENCRYPTED"
    SOURCE_PDF_INVALID = "SOURCE_PDF_INVALID"
    SOURCE_SCANNED_PDF = "SOURCE_SCANNED_PDF"
    SOURCE_EXTRACTION_FAILED = "SOURCE_EXTRACTION_FAILED"
    SOURCE_EXTRACTION_QUALITY = "SOURCE_EXTRACTION_QUALITY"
    SOURCE_PARSER_TIMEOUT = "SOURCE_PARSER_TIMEOUT"
    SOURCE_PARSER_RESOURCE_LIMIT = "SOURCE_PARSER_RESOURCE_LIMIT"
    CLAUSE_TOO_LARGE = "CLAUSE_TOO_LARGE"
    CLAUSE_EVIDENCE_INVALID = "CLAUSE_EVIDENCE_INVALID"
    DOMAIN_PACK_INVALID = "DOMAIN_PACK_INVALID"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_READY = "JOB_NOT_READY"
    PROVIDER_TRANSIENT = "PROVIDER_TRANSIENT"
    PROVIDER_REFUSAL = "PROVIDER_REFUSAL"
    PROVIDER_OUTPUT_INVALID = "PROVIDER_OUTPUT_INVALID"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(StrictModel):
    code: ErrorCode
    message: str
    retryable: bool
    source_id: Identifier | None = None
    details: dict[str, Any]


class ErrorResponse(StrictModel):
    error: ErrorDetail
    trace_id: Identifier


class BriefParserError(Exception):
    """Expected failure carrying only caller-safe error metadata."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        source_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.source_id = source_id
        self.details = {} if details is None else details

    def to_response(self, *, trace_id: str) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorDetail(
                code=self.code,
                message=self.safe_message,
                retryable=self.retryable,
                source_id=self.source_id,
                details=self.details,
            ),
            trace_id=trace_id,
        )
