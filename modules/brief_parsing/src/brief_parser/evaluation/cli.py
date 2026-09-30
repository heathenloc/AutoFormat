"""Command-line release gate for checked-in Golden Dataset predictions."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from brief_parser.evaluation.dataset import GoldenDatasetError, load_golden_dataset
from brief_parser.evaluation.evaluator import evaluate_dataset
from brief_parser.evaluation.io import (
    EvaluationInputError,
    load_predictions,
    load_pricing,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brief-parser-eval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_golden_dataset(args.dataset)
        predictions = load_predictions(args.predictions)
        pricing = None if args.pricing is None else load_pricing(args.pricing)
        report = evaluate_dataset(dataset, predictions, pricing=pricing)
        write_report(report, args.output)
    except (GoldenDatasetError, EvaluationInputError, ValueError) as exc:
        parser = _parser()
        parser.error(str(exc))
    print(args.output.resolve())
    return 0 if report.passed else 2
