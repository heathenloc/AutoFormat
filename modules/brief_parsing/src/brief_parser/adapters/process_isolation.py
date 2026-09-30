"""Linux subprocess boundary for untrusted deterministic document parsing."""

from __future__ import annotations

import multiprocessing
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from types import ModuleType
from typing import cast

from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.domain.document import ExtractedDocument
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource


@dataclass(frozen=True, slots=True)
class ParserProcessLimits:
    """Per-source Linux process limits, independent of container-level limits."""

    wall_timeout_seconds: float = 60.0
    cpu_time_seconds: int = 60
    address_space_bytes: int = 1024 * 1024 * 1024
    file_size_bytes: int = 256 * 1024 * 1024
    open_files: int = 128

    def __post_init__(self) -> None:
        if (
            self.wall_timeout_seconds <= 0
            or self.cpu_time_seconds <= 0
            or self.address_space_bytes <= 0
            or self.file_size_bytes <= 0
            or self.open_files <= 0
        ):
            raise ValueError("parser process limits must be positive")


def hard_process_isolation_supported() -> bool:
    """Return whether the approved Linux rlimit boundary is available."""

    return sys.platform.startswith("linux")


class ProcessIsolatedDocumentIngestor:
    """Run each format parser in a fresh spawn-process with hard resource limits."""

    def __init__(self, limits: ParserProcessLimits | None = None) -> None:
        if not hard_process_isolation_supported():
            raise RuntimeError("parser process isolation requires Linux")
        self._limits = limits or ParserProcessLimits()
        self._context = multiprocessing.get_context("spawn")

    def ingest(self, source: SecuredSource) -> ExtractedDocument:
        receive, send = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_parser_worker,
            args=(source, self._limits, send),
            name=f"brief-parser-{source.source_id}",
        )
        process.start()
        send.close()
        try:
            if not receive.poll(self._limits.wall_timeout_seconds):
                _kill_process_group(process)
                raise BriefParserError(
                    ErrorCode.SOURCE_PARSER_TIMEOUT,
                    "文档解析超过允许执行时间。",
                    source_id=source.source_id,
                    details={
                        "timeout_seconds": self._limits.wall_timeout_seconds,
                    },
                )
            try:
                payload = receive.recv()
            except EOFError as exc:
                process.join(timeout=1)
                raise _worker_exit_error(source.source_id, process.exitcode) from exc
        finally:
            receive.close()
            process.join(timeout=1)
            if process.is_alive():
                _kill_process_group(process)
            process.join(timeout=1)

        if not isinstance(payload, dict):
            raise BriefParserError(
                ErrorCode.SOURCE_EXTRACTION_FAILED,
                "文档解析进程返回了无效结果。",
                source_id=source.source_id,
            )
        status = payload.get("status")
        if status == "ok":
            return ExtractedDocument.model_validate(payload.get("document"))
        if status == "brief_parser_error":
            raw_code = payload.get("code")
            try:
                code = ErrorCode(str(raw_code))
            except ValueError:
                code = ErrorCode.SOURCE_EXTRACTION_FAILED
            raw_details = payload.get("details")
            details = raw_details if isinstance(raw_details, dict) else {}
            raw_source_id = payload.get("source_id")
            return_source_id = (
                raw_source_id if isinstance(raw_source_id, str) else source.source_id
            )
            raise BriefParserError(
                code,
                str(payload.get("message") or "文档解析失败。"),
                retryable=bool(payload.get("retryable", False)),
                source_id=return_source_id,
                details=details,
            )
        if status == "resource_limit":
            raise BriefParserError(
                ErrorCode.SOURCE_PARSER_RESOURCE_LIMIT,
                "文档解析超过允许的进程资源上限。",
                source_id=source.source_id,
                details={"resource": str(payload.get("resource") or "unknown")},
            )
        raise BriefParserError(
            ErrorCode.SOURCE_EXTRACTION_FAILED,
            "文档解析进程异常终止。",
            source_id=source.source_id,
        )


def _parser_worker(
    source: SecuredSource,
    limits: ParserProcessLimits,
    connection: Connection,
) -> None:
    try:
        setsid = cast(Callable[[], int], vars(os)["setsid"])
        setsid()
        _apply_linux_resource_limits(limits)
        document = DocumentIngestor().ingest(source)
        connection.send(
            {
                "status": "ok",
                "document": document.model_dump(mode="json"),
            }
        )
    except BriefParserError as exc:
        connection.send(
            {
                "status": "brief_parser_error",
                "code": exc.code.value,
                "message": exc.safe_message,
                "retryable": exc.retryable,
                "source_id": exc.source_id or source.source_id,
                "details": exc.details,
            }
        )
    except MemoryError:
        connection.send({"status": "resource_limit", "resource": "address_space"})
    except BaseException:
        connection.send({"status": "internal_error"})
    finally:
        connection.close()


def _apply_linux_resource_limits(limits: ParserProcessLimits) -> None:
    if not hard_process_isolation_supported():
        raise RuntimeError("Linux resource limits are unavailable")
    resource = import_module("resource")
    _set_limit(resource, _resource_id(resource, "RLIMIT_AS"), limits.address_space_bytes)
    _set_limit(resource, _resource_id(resource, "RLIMIT_FSIZE"), limits.file_size_bytes)
    _set_limit(resource, _resource_id(resource, "RLIMIT_NOFILE"), limits.open_files)
    _set_limit(resource, _resource_id(resource, "RLIMIT_CORE"), 0)
    cpu_resource = _resource_id(resource, "RLIMIT_CPU")
    cpu_soft = _clamp_to_hard_limit(
        resource,
        cpu_resource,
        limits.cpu_time_seconds,
    )
    cpu_hard = _clamp_to_hard_limit(
        resource,
        cpu_resource,
        limits.cpu_time_seconds + 1,
    )
    setrlimit = cast(
        Callable[[int, tuple[int, int]], None],
        resource.setrlimit,
    )
    setrlimit(cpu_resource, (cpu_soft, max(cpu_soft, cpu_hard)))


def _set_limit(resource: ModuleType, resource_id: int, requested: int) -> None:
    bounded = _clamp_to_hard_limit(resource, resource_id, requested)
    setrlimit = cast(
        Callable[[int, tuple[int, int]], None],
        resource.setrlimit,
    )
    setrlimit(resource_id, (bounded, bounded))


def _clamp_to_hard_limit(
    resource: ModuleType,
    resource_id: int,
    requested: int,
) -> int:
    getrlimit = cast(
        Callable[[int], tuple[int, int]],
        resource.getrlimit,
    )
    _, hard = getrlimit(resource_id)
    infinity = cast(int, resource.RLIM_INFINITY)
    if hard == infinity:
        return requested
    return min(requested, hard)


def _resource_id(resource: ModuleType, name: str) -> int:
    return cast(int, getattr(resource, name))


def _kill_process_group(process: BaseProcess) -> None:
    if not process.is_alive():
        return
    pid = process.pid
    if pid is not None:
        try:
            killpg = cast(Callable[[int, int], None], vars(os)["killpg"])
            killpg(pid, _signal_number("SIGKILL"))
        except ProcessLookupError:
            pass
        except PermissionError:
            process.kill()
    if process.is_alive():
        process.kill()


def _worker_exit_error(source_id: str, exit_code: int | None) -> BriefParserError:
    resource_signals = {
        -_signal_number("SIGKILL"),
        -_signal_number("SIGXCPU"),
        -_signal_number("SIGXFSZ"),
    }
    if exit_code in resource_signals:
        return BriefParserError(
            ErrorCode.SOURCE_PARSER_RESOURCE_LIMIT,
            "文档解析超过允许的进程资源上限。",
            source_id=source_id,
            details={"exit_code": exit_code},
        )
    return BriefParserError(
        ErrorCode.SOURCE_EXTRACTION_FAILED,
        "文档解析进程异常终止。",
        source_id=source_id,
        details={"exit_code": exit_code},
    )


def _signal_number(name: str) -> int:
    return cast(int, getattr(signal, name))
