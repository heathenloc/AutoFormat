"""Implement the non-trivial standalone CLI commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from brief_parser.adapters.artifact_store import ArtifactDirectoryStore
from brief_parser.api.app import create_app
from brief_parser.application.service import ParseServiceRequest, TextSourceInput
from brief_parser.bootstrap import build_domain_pack_loader, build_service
from brief_parser.config import Settings
from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics
from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.enums import Readiness
from brief_parser.domain.execution_brief import ExecutionBrief
from brief_parser.domain.pipeline import ParseManifest
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.renderers.markdown import MarkdownResultRenderer
from brief_parser.version import (
    DOMAIN_PACK_SCHEMA_VERSION,
    EXECUTION_BRIEF_SCHEMA_VERSION,
    PARSE_BUNDLE_VERSION,
    PARSE_MANIFEST_SCHEMA_VERSION,
    REQUIREMENT_IR_SCHEMA_VERSION,
)

SUCCESS_EXIT_CODE = 0
INCOMPLETE_EXIT_CODE = 2
INVALID_INPUT_EXIT_CODE = 3
RETRYABLE_PROVIDER_EXIT_CODE = 4
INTERNAL_ERROR_EXIT_CODE = 5
CANCELLED_EXIT_CODE = 130


async def _parse(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    service = build_service(settings)
    text_sources: tuple[TextSourceInput, ...] = ()
    source_paths: tuple[Path, ...] = ()
    if args.stdin:
        text_sources = (TextSourceInput(text=sys.stdin.read()),)
    else:
        source_paths = (Path(args.input),)

    bundle = await service.parse_with_timeout(
        ParseServiceRequest(
            request_id=f"req_{uuid4().hex}",
            domain_pack_id=args.domain,
            domain_pack_version=getattr(args, "domain_version", None),
            requested_task_types=tuple(args.task),
            source_paths=source_paths,
            text_sources=text_sources,
            locale=getattr(args, "locale", "zh-CN"),
        ),
        timeout_seconds=settings.job_timeout_seconds,
    )
    write_result = ArtifactDirectoryStore().write(bundle, Path(args.output))
    print(
        json.dumps(
            {
                "artifact_id": bundle.manifest.artifact_id,
                "output_dir": str(write_result.output_dir),
                "readiness": bundle.requirement_ir.readiness.value,
                "reused_existing": write_result.reused_existing,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if bundle.requirement_ir.readiness == Readiness.INCOMPLETE:
        return INCOMPLETE_EXIT_CODE
    return SUCCESS_EXIT_CODE


def _validate_domain_pack(path: Path) -> int:
    loader = build_domain_pack_loader()
    pack = loader.load_json(path) if path.suffix.lower() == ".json" else loader.load_yaml(path)
    print(
        json.dumps(
            {"id": pack.id, "schema_version": pack.schema_version, "version": pack.version},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return SUCCESS_EXIT_CODE


def _load_json_contract(path: Path) -> tuple[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BriefParserError(
            ErrorCode.INVALID_REQUEST,
            "结果文件不是可读取的 UTF-8 JSON。",
        ) from exc
    if not isinstance(payload, dict):
        raise BriefParserError(ErrorCode.INVALID_REQUEST, "结果 JSON 顶层必须是对象。")

    contracts: dict[str, tuple[str, type[Any]]] = {
        PARSE_BUNDLE_VERSION: ("parse_bundle", ParseBundle),
        PARSE_MANIFEST_SCHEMA_VERSION: ("parse_manifest", ParseManifest),
        REQUIREMENT_IR_SCHEMA_VERSION: ("requirement_ir", RequirementIR),
        EXECUTION_BRIEF_SCHEMA_VERSION: ("execution_brief", ExecutionBrief),
        DOMAIN_PACK_SCHEMA_VERSION: ("domain_pack", DomainPack),
        "parse-diagnostics/1.0": ("parse_diagnostics", ParseDiagnostics),
    }
    bundle_version = payload.get("bundle_version")
    schema_version = payload.get("schema_version")
    key = bundle_version if isinstance(bundle_version, str) else schema_version
    if not isinstance(key, str):
        raise BriefParserError(ErrorCode.INVALID_REQUEST, "无法识别结果契约版本。")
    selected = contracts.get(key)
    if selected is None:
        raise BriefParserError(ErrorCode.INVALID_REQUEST, "无法识别结果契约版本。")
    name, model = selected
    return name, model.model_validate(payload)


def _validate_result(path: Path) -> int:
    version: str
    if path.is_dir():
        bundle = ArtifactDirectoryStore().read(path)
        name = "artifact_directory"
        version = bundle.bundle_version
    else:
        name, value = _load_json_contract(path)
        version = str(
            getattr(value, "bundle_version", None) or getattr(value, "schema_version", "unknown")
        )
    print(json.dumps({"contract": name, "version": version}, sort_keys=True))
    return SUCCESS_EXIT_CODE


def _render(path: Path, output: Path) -> int:
    if path.is_dir():
        markdown = ArtifactDirectoryStore().read(path).renderings.markdown
    else:
        name, value = _load_json_contract(path)
        if name == "parse_bundle":
            markdown = value.renderings.markdown
        elif name == "requirement_ir":
            markdown = MarkdownResultRenderer().render(value, {})
        else:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "render 仅接受 Parse Bundle、Requirement IR 或 Artifact 目录。",
            )
    _atomic_write_text(output, markdown.rstrip() + "\n")
    print(str(output.resolve()))
    return SUCCESS_EXIT_CODE


def _atomic_write_text(path: Path, content: str) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return SUCCESS_EXIT_CODE


def _exit_for_error(error: BriefParserError) -> int:
    print(f"{error.code.value}: {error.safe_message}", file=sys.stderr)
    if error.code == ErrorCode.PROVIDER_TRANSIENT or error.retryable:
        return RETRYABLE_PROVIDER_EXIT_CODE
    if error.code == ErrorCode.INTERNAL_ERROR:
        return INTERNAL_ERROR_EXIT_CODE
    return INVALID_INPUT_EXIT_CODE


def run_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "parse":
            return asyncio.run(_parse(args))
        if args.command == "validate-domain-pack":
            return _validate_domain_pack(Path(args.path))
        if args.command == "validate-result":
            return _validate_result(Path(args.path))
        if args.command == "render":
            return _render(Path(args.path), Path(args.output))
        if args.command == "serve":
            return _serve(args)
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return CANCELLED_EXIT_CODE
    except BriefParserError as error:
        return _exit_for_error(error)
    except ValidationError as error:
        print(
            f"{ErrorCode.INVALID_REQUEST.value}: 配置或输入无法通过校验"
            f"({error.error_count()} 项)。",
            file=sys.stderr,
        )
        return INVALID_INPUT_EXIT_CODE
    except (OSError, ValueError) as error:
        print(f"{ErrorCode.INVALID_REQUEST.value}: {error}", file=sys.stderr)
        return INVALID_INPUT_EXIT_CODE
    except Exception:
        print(
            f"{ErrorCode.INTERNAL_ERROR.value}: Brief Parser 执行失败。",
            file=sys.stderr,
        )
        return INTERNAL_ERROR_EXIT_CODE
    return INTERNAL_ERROR_EXIT_CODE
