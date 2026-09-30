import sys

import pytest

from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.adapters.process_isolation import (
    ParserProcessLimits,
    ProcessIsolatedDocumentIngestor,
)
from brief_parser.errors import BriefParserError, ErrorCode

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="hard parser isolation is an approved Linux runtime guarantee",
)


def _secured_text():  # type: ignore[no-untyped-def]
    return FileSecurityValidator().secure_text(
        "成片不得超过 60 秒，并且必须出现品牌名称。",
        source_id="src_isolation",
        client_source_id="brief",
    )


def test_linux_parser_process_returns_validated_document() -> None:
    document = ProcessIsolatedDocumentIngestor().ingest(_secured_text())

    assert document.source_manifest.source_id == "src_isolation"
    assert document.source_manifest.parser_id == "direct-text"
    assert document.blocks


def test_linux_parser_process_enforces_wall_timeout() -> None:
    ingestor = ProcessIsolatedDocumentIngestor(
        ParserProcessLimits(wall_timeout_seconds=0.000_001)
    )

    with pytest.raises(BriefParserError) as error:
        ingestor.ingest(_secured_text())

    assert error.value.code == ErrorCode.SOURCE_PARSER_TIMEOUT
    assert error.value.source_id == "src_isolation"
