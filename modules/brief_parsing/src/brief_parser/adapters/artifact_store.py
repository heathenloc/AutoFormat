"""Atomic filesystem persistence for standalone Parse Bundle artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics, ParseRenderings
from brief_parser.domain.execution_brief import ExecutionBrief
from brief_parser.domain.pipeline import ParseManifest
from brief_parser.domain.requirement_ir import RequirementIR
from brief_parser.errors import BriefParserError, ErrorCode

_SAFE_TASK_TYPE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")


@dataclass(frozen=True, slots=True)
class ArtifactWriteResult:
    output_dir: Path
    files: tuple[Path, ...]
    reused_existing: bool


class ArtifactDirectoryStore:
    """Write all public artifacts together and never expose a partial directory."""

    def write(self, bundle: ParseBundle, output_dir: Path) -> ArtifactWriteResult:
        target = output_dir.resolve()
        if target.exists():
            existing = self.read(target)
            if (
                existing.manifest.request_fingerprint != bundle.manifest.request_fingerprint
                or existing.manifest.artifact_id != bundle.manifest.artifact_id
            ):
                raise BriefParserError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "输出目录已包含另一请求的 Artifact。",
                    details={"output_dir": str(target)},
                )
            return ArtifactWriteResult(
                output_dir=target,
                files=self._expected_paths(target, existing),
                reused_existing=True,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
        try:
            payloads = self._payloads(bundle)
            for filename, content in payloads.items():
                self._write_file(temporary / filename, content)
            try:
                temporary.rename(target)
            except FileExistsError:
                existing = self.read(target)
                if existing.manifest.request_fingerprint != bundle.manifest.request_fingerprint:
                    raise BriefParserError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "输出目录被另一请求并发占用。",
                    ) from None
                return ArtifactWriteResult(
                    output_dir=target,
                    files=self._expected_paths(target, existing),
                    reused_existing=True,
                )
            return ArtifactWriteResult(
                output_dir=target,
                files=tuple(target / filename for filename in payloads),
                reused_existing=False,
            )
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def read(self, output_dir: Path) -> ParseBundle:
        root = output_dir.resolve()
        if not root.is_dir() or root.is_symlink():
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "Artifact 路径不是可读取的普通目录。",
            )
        try:
            manifest = ParseManifest.model_validate_json(
                (root / "manifest.json").read_text(encoding="utf-8")
            )
            requirement_ir = RequirementIR.model_validate_json(
                (root / "requirement-ir.json").read_text(encoding="utf-8")
            )
            diagnostics = ParseDiagnostics.model_validate_json(
                (root / "diagnostics.json").read_text(encoding="utf-8")
            )
            markdown = (root / "result.md").read_text(encoding="utf-8")
            execution_briefs = {
                task_type: ExecutionBrief.model_validate_json(
                    (root / self._execution_filename(task_type)).read_text(encoding="utf-8")
                )
                for task_type in manifest.requested_task_types
            }
            return ParseBundle(
                manifest=manifest,
                requirement_ir=requirement_ir,
                execution_briefs=execution_briefs,
                renderings=ParseRenderings(markdown=markdown),
                diagnostics=diagnostics,
            )
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "Artifact 目录缺失文件或无法通过契约校验。",
            ) from exc

    def _payloads(self, bundle: ParseBundle) -> dict[str, str]:
        payloads = {
            "manifest.json": _json_text(bundle.manifest.model_dump(mode="json")),
            "requirement-ir.json": _json_text(bundle.requirement_ir.model_dump(mode="json")),
            "diagnostics.json": _json_text(bundle.diagnostics.model_dump(mode="json")),
            "result.md": bundle.renderings.markdown.rstrip() + "\n",
        }
        for task_type, brief in sorted(bundle.execution_briefs.items()):
            payloads[self._execution_filename(task_type)] = _json_text(
                brief.model_dump(mode="json")
            )
        return payloads

    def _expected_paths(self, root: Path, bundle: ParseBundle) -> tuple[Path, ...]:
        return tuple(root / filename for filename in self._payloads(bundle))

    @staticmethod
    def _execution_filename(task_type: str) -> str:
        if not _SAFE_TASK_TYPE.fullmatch(task_type) or ".." in task_type:
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "任务类型不能安全映射为 Artifact 文件名。",
            )
        return f"execution-brief.{task_type}.json"

    @staticmethod
    def _write_file(path: Path, content: str) -> None:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())


def _json_text(payload: Any) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
