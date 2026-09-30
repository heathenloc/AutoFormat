"""Exercise the host-neutral application service under bounded concurrency."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from brief_parser.application.service import ParseServiceRequest, TextSourceInput
from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.evaluation.io import write_json_model
from brief_parser.evaluation.load import LoadProbeConfig, run_load_probe


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brief-parser-load")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain", default="advertising_brief")
    parser.add_argument("--domain-version", default="1.0.0")
    parser.add_argument("--task", action="append", default=["write_ad_script"])
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-p95-ms", type=int, default=30_000)
    return parser


async def _run(args: argparse.Namespace) -> int:
    text = args.input.read_text(encoding="utf-8")
    service = build_service(Settings.from_env())
    config = LoadProbeConfig(
        request_count=args.requests,
        concurrency=args.concurrency,
        max_p95_ms=args.max_p95_ms,
    )

    async def operation(ordinal: int) -> object:
        return await service.parse(
            ParseServiceRequest(
                request_id=f"req_load_{ordinal:05d}",
                domain_pack_id=args.domain,
                domain_pack_version=args.domain_version,
                requested_task_types=tuple(args.task),
                text_sources=(TextSourceInput(text=text),),
            )
        )

    report = await run_load_probe(operation, config)
    write_json_model(report, args.output)
    print(args.output.resolve())
    return 0 if report.passed else 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))
