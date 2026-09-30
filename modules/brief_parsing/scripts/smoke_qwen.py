"""Make one minimal, synthetic Qwen structured-output call."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Literal

from openai import APIStatusError
from pydantic import ValidationError

from brief_parser.bootstrap import build_model_provider
from brief_parser.config import Settings
from brief_parser.domain.base import StrictModel
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError
from brief_parser.ports.model_provider import ModelRequestContext, ProviderMessage


class QwenSmokeOutput(StrictModel):
    status: Literal["ok"]
    source_kind: Literal["synthetic"]


async def _run() -> None:
    settings = Settings.from_env()
    if settings.provider != "qwen":
        raise SystemExit("set BRIEF_PARSER_PROVIDER=qwen before running this smoke test")
    provider = build_model_provider(settings)
    result = await provider.structured_generate(
        role=ModelRole.EXTRACTOR,
        messages=[
            ProviderMessage(
                role="system",
                content=(
                    "Return the requested structured object. "
                    "Do not add facts beyond the synthetic input."
                ),
            ),
            ProviderMessage(
                role="user",
                content="Synthetic connectivity probe. status=ok; source_kind=synthetic.",
            ),
        ],
        output_schema=QwenSmokeOutput,
        request_context=ModelRequestContext(
            request_id="req_qwen_smoke",
            trace_id="trace_qwen_smoke",
        ),
    )
    if result.output is None:
        raise SystemExit(
            f"Qwen smoke test did not complete: {result.completion_status}"
        )
    print(
        json.dumps(
            {
                "provider": result.provider_alias,
                "model": result.model_id,
                "status": result.completion_status,
                "input_tokens": result.token_usage.input_tokens,
                "output_tokens": result.token_usage.output_tokens,
                "provider_request_id_present": result.provider_request_id is not None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main() -> int:
    try:
        asyncio.run(_run())
    except BriefParserError as exc:
        cause = exc.__cause__
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": exc.code.value,
                    "http_status": (
                        cause.status_code if isinstance(cause, APIStatusError) else None
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except (ValidationError, ValueError):
        print('{"status":"error","error_code":"CONFIG_INVALID"}', file=sys.stderr)
        return 1
    except Exception:
        print('{"status":"error","error_code":"UNEXPECTED"}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
