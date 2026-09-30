from pathlib import Path

import pytest

from brief_parser.adapters.fake_provider import FakeModelProvider
from brief_parser.application.service import ParseServiceRequest, TextSourceInput
from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError, ErrorCode
from tests.helpers import make_text_pdf


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "mode": "standalone",
        "environment": "test",
        "provider": "fake",
        "storage_dir": tmp_path / "var",
        "sqlite_path": tmp_path / "var" / "jobs.sqlite3",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _request(
    *,
    source_paths: tuple[Path, ...] = (),
    text_sources: tuple[TextSourceInput, ...] = (),
) -> ParseServiceRequest:
    return ParseServiceRequest(
        request_id="req_resource_limits",
        domain_pack_id="advertising_brief",
        requested_task_types=("write_ad_script",),
        source_paths=source_paths,
        text_sources=text_sources,
    )


async def test_rejects_too_many_sources_before_provider_use(tmp_path: Path) -> None:
    provider = FakeModelProvider()
    service = build_service(_settings(tmp_path, max_sources=2), provider=provider)

    with pytest.raises(BriefParserError) as error:
        await service.parse(
            _request(
                text_sources=tuple(
                    TextSourceInput(text=f"synthetic source {index}")
                    for index in range(3)
                )
            )
        )

    assert error.value.code == ErrorCode.INVALID_REQUEST
    assert error.value.details == {"source_count": 3, "max_sources": 2}
    assert sum(provider.call_count.values()) == 0


async def test_rejects_aggregate_pdf_pages_before_provider_use(tmp_path: Path) -> None:
    paths = tuple(tmp_path / f"brief-{index}.pdf" for index in range(2))
    for path in paths:
        path.write_bytes(
            make_text_pdf(
                [
                    ["Enough synthetic text on page one."],
                    ["Enough synthetic text on page two."],
                ]
            )
        )
    provider = FakeModelProvider()
    service = build_service(_settings(tmp_path, max_pages=3), provider=provider)

    with pytest.raises(BriefParserError) as error:
        await service.parse(_request(source_paths=paths))

    assert error.value.code == ErrorCode.SOURCE_TOO_MANY_PAGES
    assert error.value.details == {
        "total_pdf_pages": 4,
        "max_total_pdf_pages": 3,
    }
    assert sum(provider.call_count.values()) == 0


async def test_rejects_aggregate_extracted_chars_before_provider_use(
    tmp_path: Path,
) -> None:
    provider = FakeModelProvider()
    service = build_service(
        _settings(tmp_path, max_extracted_chars=10),
        provider=provider,
    )

    with pytest.raises(BriefParserError) as error:
        await service.parse(
            _request(
                text_sources=(
                    TextSourceInput(text="abcdef", client_source_id="first"),
                    TextSourceInput(text="ghijkl", client_source_id="second"),
                )
            )
        )

    assert error.value.code == ErrorCode.SOURCE_EXTRACTED_TOO_LARGE
    assert error.value.details == {
        "total_extracted_chars": 12,
        "max_total_extracted_chars": 10,
    }
    assert sum(provider.call_count.values()) == 0
