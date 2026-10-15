"""Pinned read-only C# and PDF.js subprocesses; never accept client index data."""
from __future__ import annotations

import json
from collections import OrderedDict
import threading
import shutil
import subprocess
from pathlib import Path

from .feedback_contracts import Contract, Hash, Key, Label, content_hash
from .feedback_store import FeedbackError
from .preview import _sha256
from pydantic import Field
from typing import Annotated, Literal


class DocxParagraph(Contract):
    object_id: Annotated[str, Field(pattern=r"^o:[a-f0-9]{24}$")]
    story_id: Key
    text: Annotated[str, Field(max_length=2000000)]
    location_label: Label
    editable: bool
    semantic_role: Key
    ordinal: Annotated[int, Field(ge=1)]


class DocxSelectionIndex(Contract):
    schema_version: Literal["selection-docx-index/1.0"]
    sha256: Hash
    paragraphs: Annotated[list[DocxParagraph], Field(max_length=50000)]


class PdfItem(Contract):
    index: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(alias="str", max_length=2000000)]
    has_eol: bool


class AcademicScopeObject(Contract):
    object_id: Key
    part: Label
    xml_path: Annotated[str, Field(max_length=4096)]
    kind: Literal["paragraph", "table", "section"]
    semantic_role: Key
    region: Key | None
    region_zone: Key | None
    chapter: Key | None
    object_ordinal: Key | None
    object_language: Key | None
    section: Annotated[int, Field(ge=0)]
    requires_manual_targeting: bool


class AcademicScopeIndex(Contract):
    schema_version: Literal["academic-docx-index/1.0"]
    sha256: Hash
    objects: Annotated[list[AcademicScopeObject], Field(max_length=60000)]


class PdfPage(Contract):
    page: Annotated[int, Field(ge=1)]
    items: Annotated[list[PdfItem], Field(max_length=100000)]


class PdfSelectionIndex(Contract):
    schema_version: Literal["selection-pdf-index/1.0"]
    pdfjs_version: Literal["6.4.299"]
    pdf_sha256: Hash
    page_count: Annotated[int, Field(ge=1)]
    pages: Annotated[list[PdfPage], Field(max_length=64)]


class SelectionIndexes:
    def __init__(self, *, node: Path, dotnet: Path, script: Path, editor_dll: Path, timeout_seconds: int = 45):
        self.node, self.dotnet, self.script, self.editor_dll = [p.resolve(strict=True) for p in (node, dotnet, script, editor_dll)]
        self.timeout_seconds = timeout_seconds
        pdfjs = script.parent.parent / "apps/web/node_modules/pdfjs-dist"
        self.files = [self.node, self.dotnet, self.script, *sorted(self.editor_dll.parent.glob("*.dll")),
                      self.editor_dll.with_suffix(".deps.json"), self.editor_dll.with_suffix(".runtimeconfig.json"),
                      pdfjs / "package.json", pdfjs / "legacy/build/pdf.mjs", pdfjs / "legacy/build/pdf.worker.mjs"]
        self.files.extend(sorted(path for directory in ("cmaps", "standard_fonts", "wasm")
                                 for path in (pdfjs / directory).rglob("*") if path.is_file()))
        if (timeout_seconds < 1 or json.loads((pdfjs / "package.json").read_text(encoding="utf-8"))["version"] != "6.4.299"):
            raise ValueError("Selection adapter configuration is invalid.")
        self.digests = [_sha256(path) for path in self.files]
        self.fingerprint = content_hash({"adapter": "selection-indexes/1.0", "files": self.digests})
        self._cache, self._cache_lock = OrderedDict(), threading.RLock()

    @classmethod
    def from_project(cls, root: Path, *, node: Path | None = None, editor_dll: Path | None = None):
        return cls(node=node or Path(shutil.which("node") or ""), dotnet=Path(shutil.which("dotnet") or ""),
            script=root / "scripts/pdf_text_index.mjs", editor_dll=editor_dll or
            root / "services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0/AutoFormat.DocxEditor.dll")

    def _check(self):
        try:
            if [_sha256(path) for path in self.files] != self.digests:
                raise ValueError()
        except (OSError, ValueError) as error:
            raise FeedbackError("validation_failed", "定位组件已变化，请重启本地应用后重新定位。") from error

    def _run(self, command, model):
        self._check()
        try:
            completed = subprocess.run([str(value) for value in command], capture_output=True, encoding="utf-8", errors="strict",
                timeout=self.timeout_seconds, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode or len(completed.stdout.encode("utf-8")) > 32 * 1024 * 1024:
                raise ValueError()
            result = model.model_validate_json(completed.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise FeedbackError("unsupported_target", "本地定位组件无法安全读取此选区，请缩小范围或检查组件。") from error
        self._check()
        return result

    def docx(self, path: Path) -> DocxSelectionIndex:
        return self._cached(path, "docx", [self.dotnet, self.editor_dll, "inspect-selection", path], DocxSelectionIndex)

    def pdf(self, path: Path, pages: list[int]) -> PdfSelectionIndex:
        return self._cached(path, ("pdf", tuple(pages)), [self.node, "--max-old-space-size=256", self.script, path, json.dumps(pages)], PdfSelectionIndex)

    def semantic(self, path: Path) -> AcademicScopeIndex:
        return self._cached(path, "semantic", [self.dotnet, self.editor_dll, "inspect-academic", path], AcademicScopeIndex)

    def _cached(self, path, kind, command, model):
        # Cache only immutable content, never mtime or a browser-supplied ID.
        # Component and source bytes are checked on every cache hit as well.
        self._check()
        digest = _sha256(path)
        key = (kind, digest)
        with self._cache_lock:
            result = self._cache.get(key)
        if result is None:
            result = self._run(command, model)
        if _sha256(path) != digest or (result.pdf_sha256 if isinstance(result, PdfSelectionIndex) else result.sha256) != digest:
            raise FeedbackError("stale_preview", "定位期间原文件发生变化。")
        self._check()
        with self._cache_lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > 32: self._cache.popitem(last=False)
        return result.model_copy(deep=True)
