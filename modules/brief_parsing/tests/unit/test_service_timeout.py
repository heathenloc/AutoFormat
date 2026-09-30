import asyncio

import pytest

from brief_parser.application.service import BriefParserService, ParseServiceRequest
from brief_parser.domain.bundle import ParseBundle
from brief_parser.errors import BriefParserError, ErrorCode


class SlowBriefParserService(BriefParserService):
    async def parse(self, request: ParseServiceRequest) -> ParseBundle:
        del request
        await asyncio.sleep(60)
        raise AssertionError("timeout should cancel the slow parse")


def _request() -> ParseServiceRequest:
    return ParseServiceRequest(
        request_id="req_timeout",
        domain_pack_id="advertising_brief",
        requested_task_types=("write_ad_script",),
    )


async def test_shared_service_timeout_returns_retryable_safe_error() -> None:
    service = object.__new__(SlowBriefParserService)

    with pytest.raises(BriefParserError) as error:
        await service.parse_with_timeout(_request(), timeout_seconds=0.01)

    assert error.value.code == ErrorCode.PROVIDER_TRANSIENT
    assert error.value.retryable is True
    assert error.value.details == {"timeout_seconds": 0.01}


async def test_shared_service_timeout_rejects_nonpositive_limit() -> None:
    service = object.__new__(SlowBriefParserService)

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        await service.parse_with_timeout(_request(), timeout_seconds=0)
