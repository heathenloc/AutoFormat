import sys

import pytest

from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.process_isolation import (
    ParserProcessLimits,
    ProcessIsolatedDocumentIngestor,
    hard_process_isolation_supported,
)
from brief_parser.bootstrap import build_document_ingestor
from brief_parser.config import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {"wall_timeout_seconds": 0},
        {"cpu_time_seconds": 0},
        {"address_space_bytes": 0},
        {"file_size_bytes": 0},
        {"open_files": 0},
    ],
)
def test_parser_process_limits_must_be_positive(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ParserProcessLimits(**overrides)


def test_hard_isolation_support_matches_linux_runtime() -> None:
    assert hard_process_isolation_supported() is sys.platform.startswith("linux")


def test_auto_isolation_has_explicit_platform_behavior() -> None:
    ingestor = build_document_ingestor(Settings.from_env({}))

    if sys.platform.startswith("linux"):
        assert isinstance(ingestor, ProcessIsolatedDocumentIngestor)
    else:
        assert isinstance(ingestor, DocumentIngestor)


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="Linux supports the approved process boundary",
)
def test_explicit_process_mode_rejects_unsupported_runtime() -> None:
    settings = Settings.from_env(
        {"BRIEF_PARSER_PARSER_ISOLATION_MODE": "process"}
    )

    with pytest.raises(RuntimeError, match="requires a Linux runtime"):
        build_document_ingestor(settings)
