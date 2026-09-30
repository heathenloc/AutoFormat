"""Run the configured provider over the versioned Golden Dataset."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from brief_parser.application.service import (
    BriefParserService,
    ParseServiceRequest,
    TextSourceInput,
)
from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.evaluation.dataset import (
    default_golden_dataset_path,
    load_golden_dataset,
)
from brief_parser.evaluation.io import write_predictions
from brief_parser.evaluation.models import GoldenCase, GoldenDataset, PredictionRecord


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brief-parser-golden-run")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=default_golden_dataset_path(),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--concurrency", type=int, default=1)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        metavar="ID",
        help="Run only this case; repeat the option to select several cases.",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        dest="all_cases",
        help="Explicitly run the complete Golden Dataset.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print selected case IDs without building a Provider or calling a model.",
    )
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow a dry run with the fake provider; it cannot satisfy release gates.",
    )
    return parser


def select_cases(
    dataset: GoldenDataset,
    *,
    case_ids: Sequence[str] | None,
    all_cases: bool,
) -> list[GoldenCase]:
    if all_cases:
        return list(dataset.cases)
    requested = list(case_ids or ())
    if not requested:
        raise ValueError("select at least one --case-id or use --all")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate --case-id values are not allowed")
    known = {case.case_id for case in dataset.cases}
    unknown = sorted(set(requested) - known)
    if unknown:
        raise ValueError(f"unknown Golden case IDs: {', '.join(unknown)}")
    selected_ids = set(requested)
    return [case for case in dataset.cases if case.case_id in selected_ids]


async def _predict(
    case: GoldenCase,
    *,
    service: BriefParserService,
    semaphore: asyncio.Semaphore,
) -> PredictionRecord:
    async with semaphore:
        try:
            bundle = await service.parse(
                ParseServiceRequest(
                    request_id=f"req_eval_{case.case_id.replace('-', '_')}",
                    domain_pack_id=case.domain_pack_id,
                    domain_pack_version=case.domain_pack_version,
                    requested_task_types=tuple(case.requested_task_types),
                    text_sources=(
                        TextSourceInput(
                            text=case.source_text,
                            client_source_id=case.case_id,
                        ),
                    ),
                    locale=case.locale,
                )
            )
        except BriefParserError as exc:
            return PredictionRecord(case_id=case.case_id, error_code=exc.code.value)
        except Exception:
            return PredictionRecord(
                case_id=case.case_id,
                error_code=ErrorCode.INTERNAL_ERROR.value,
            )
        return PredictionRecord(
            case_id=case.case_id,
            requirement_ir=bundle.requirement_ir.model_dump(mode="json"),
            provider_calls=bundle.manifest.provider_calls,
        )


async def _run(
    cases: Sequence[GoldenCase],
    *,
    settings: Settings,
    concurrency: int,
) -> list[PredictionRecord]:
    service = build_service(settings)
    semaphore = asyncio.Semaphore(concurrency)
    return list(
        await asyncio.gather(
            *(
                _predict(case, service=service, semaphore=semaphore)
                for case in cases
            )
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        dataset = load_golden_dataset(args.dataset)
        cases = select_cases(
            dataset,
            case_ids=args.case_ids,
            all_cases=args.all_cases,
        )
        if args.concurrency <= 0:
            raise ValueError("concurrency must be positive")
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan:
        print(f"selected_cases={len(cases)}; provider_calls=0")
        for case in cases:
            print(case.case_id)
        return 0
    if args.output is None:
        parser.error("--output is required unless --plan is set")
    settings = Settings.from_env()
    if settings.provider == "fake" and not args.allow_fake:
        parser.error(
            "release predictions require a real configured provider; "
            "use --allow-fake only for a non-release dry run"
        )
    try:
        records = asyncio.run(
            _run(cases, settings=settings, concurrency=args.concurrency)
        )
        write_predictions(records, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())
    return 0 if all(record.requirement_ir is not None for record in records) else 2
