"""Standalone Brief Parser CLI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from brief_parser.cli.commands import run_command
from brief_parser.version import (
    DOMAIN_PACK_SCHEMA_VERSION,
    EVALUATION_REPORT_SCHEMA_VERSION,
    EXECUTION_BRIEF_SCHEMA_VERSION,
    GOLDEN_DATASET_SCHEMA_VERSION,
    PARSE_BUNDLE_VERSION,
    PARSE_MANIFEST_SCHEMA_VERSION,
    PIPELINE_VERSION,
    REQUIREMENT_IR_SCHEMA_VERSION,
    __version__,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brief-parser",
        description="Evidence-backed brief and requirement parsing.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse = subparsers.add_parser("parse", help="Parse a brief into versioned artifacts.")
    source = parse.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", metavar="PATH")
    source.add_argument("--stdin", action="store_true")
    parse.add_argument("--domain", required=True)
    parse.add_argument("--domain-version")
    parse.add_argument("--locale", default="zh-CN")
    parse.add_argument("--task", action="append", required=True)
    parse.add_argument("--output", required=True, metavar="DIR")

    validate_pack = subparsers.add_parser(
        "validate-domain-pack", help="Validate and compile a declarative Domain Pack."
    )
    validate_pack.add_argument("path")

    validate_result = subparsers.add_parser(
        "validate-result", help="Validate a Requirement IR or Execution Brief."
    )
    validate_result.add_argument("path")

    render = subparsers.add_parser("render", help="Render a validated Requirement IR.")
    render.add_argument("path")
    render.add_argument("--output", required=True, metavar="PATH")

    serve = subparsers.add_parser("serve", help="Start the standalone API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    version = subparsers.add_parser("version", help="Print package and contract versions.")
    version.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _print_version(*, as_json: bool) -> int:
    versions = {
        "package": __version__,
        "pipeline": PIPELINE_VERSION,
        "parse_manifest": PARSE_MANIFEST_SCHEMA_VERSION,
        "parse_bundle": PARSE_BUNDLE_VERSION,
        "requirement_ir": REQUIREMENT_IR_SCHEMA_VERSION,
        "execution_brief": EXECUTION_BRIEF_SCHEMA_VERSION,
        "domain_pack": DOMAIN_PACK_SCHEMA_VERSION,
        "golden_dataset": GOLDEN_DATASET_SCHEMA_VERSION,
        "evaluation_report": EVALUATION_REPORT_SCHEMA_VERSION,
    }
    if as_json:
        print(json.dumps(versions, ensure_ascii=False, sort_keys=True))
    else:
        print(f"brief-parser {__version__} (pipeline {PIPELINE_VERSION})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        return _print_version(as_json=args.as_json)
    return run_command(args)
