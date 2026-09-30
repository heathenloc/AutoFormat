"""Bounded dual-file intake using the copied Brief parser's parse-only path.

Only the Brief enters the parser. The paper is checked and stored as immutable V0;
no model output is promoted to an executable rule by this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.application.service import ParseServiceRequest
from brief_parser.domain.academic_bundle import AcademicParseBundle

from .version_store import (
    AcademicIntakeInput, VersionRecord, VersionStore, VersionStoreError,
    _safe_remove_directory,
)


_ID = re.compile(r"^[a-f0-9]{32}$")
_SUFFIXES = {".txt", ".docx", ".pdf"}
_MAX_BUNDLE_BYTES = 10 * 1024 * 1024


class AcademicParseService(Protocol):
    async def parse_academic_with_timeout(
        self, request: ParseServiceRequest, *, timeout_seconds: float,
    ) -> AcademicParseBundle: ...


@dataclass(frozen=True, slots=True)
class AcademicIntakeResult:
    version: VersionRecord
    bundle: AcademicParseBundle
    replayed: bool


class AcademicTaskIntake:
    """Parse one Brief, then publish it with V0 in one version-store transaction."""

    def __init__(
        self, *, store: VersionStore, service: AcademicParseService,
        max_file_bytes: int = 20 * 1024 * 1024,
        parse_timeout_seconds: float = 120,
    ) -> None:
        if (max_file_bytes <= 0 or max_file_bytes > 20 * 1024 * 1024 or
                parse_timeout_seconds <= 0):
            raise ValueError("Academic intake limits must be positive.")
        self.store = store
        self.service = service
        self.max_file_bytes = max_file_bytes
        self.parse_timeout_seconds = parse_timeout_seconds
        self.security = FileSecurityValidator()
        self._lock = asyncio.Lock()

    @staticmethod
    def _suffix(filename: str, allowed: set[str]) -> str:
        if (not filename or len(filename) > 255 or
                "/" in filename or "\\" in filename or "\x00" in filename):
            raise VersionStoreError("unsafe_input", "Upload filename is invalid.")
        suffix = Path(filename).suffix.lower()
        if suffix not in allowed:
            raise VersionStoreError("unsafe_input", "Upload file type is unsupported.")
        return suffix

    @staticmethod
    def _fingerprint(brief: bytes, paper: bytes) -> str:
        return hashlib.sha256(
            b"academic-intake/1.0\0" + hashlib.sha256(brief).digest() +
            hashlib.sha256(paper).digest()
        ).hexdigest()

    async def create(
        self, *, request_id: str, brief_filename: str, brief: bytes,
        paper_filename: str, paper: bytes,
        model_processing_acknowledged: bool,
    ) -> AcademicIntakeResult:
        async with self._lock:
            return await self._create_unlocked(
                request_id=request_id, brief_filename=brief_filename, brief=brief,
                paper_filename=paper_filename, paper=paper,
                model_processing_acknowledged=model_processing_acknowledged,
            )

    async def _create_unlocked(
        self, *, request_id: str, brief_filename: str, brief: bytes,
        paper_filename: str, paper: bytes,
        model_processing_acknowledged: bool,
    ) -> AcademicIntakeResult:
        if model_processing_acknowledged is not True:
            raise VersionStoreError(
                "needs_user_input", "Acknowledge Brief model processing before upload.")
        if not _ID.fullmatch(request_id):
            raise VersionStoreError("unsafe_input", "Intake request ID is invalid.")
        brief_suffix = self._suffix(brief_filename, _SUFFIXES)
        self._suffix(paper_filename, {".docx"})
        if (not brief or not paper or len(brief) > self.max_file_bytes or
                len(paper) > self.max_file_bytes):
            raise VersionStoreError("unsafe_input", "Upload is empty or exceeds its size limit.")
        fingerprint = self._fingerprint(brief, paper)
        prior = self.store.find_academic_intake_request(request_id, fingerprint)
        if prior is not None:
            return AcademicIntakeResult(prior, self.load_bundle(prior.task_id), True)

        stage = self.store._new_stage()
        try:
            brief_path = stage / f"brief{brief_suffix}"
            paper_path = stage / "paper.docx"
            bundle_path = stage / "parse-bundle.json"
            brief_path.write_bytes(brief)
            paper_path.write_bytes(paper)
            secured_brief = self.security.secure_file(
                brief_path, source_id="src_001", client_source_id="school-brief",
                language_hints=("zh-CN",),
            )
            secured_paper = self.security.secure_file(
                paper_path, source_id="paper_001", client_source_id="paper",
                language_hints=("zh-CN",),
            )
            if secured_paper.kind != "docx":
                raise VersionStoreError("unsafe_input", "Paper must be a DOCX file.")
            request = ParseServiceRequest(
                request_id=request_id, domain_pack_id="academic_paper",
                requested_task_types=("format_academic_paper",),
                source_paths=(brief_path,),
            )
            parsed = await self.service.parse_academic_with_timeout(
                request, timeout_seconds=self.parse_timeout_seconds)
            try:
                bundle = AcademicParseBundle.model_validate_json(parsed.model_dump_json())
            except (AttributeError, TypeError, ValueError) as error:
                raise VersionStoreError("validation_failed", "Academic parse result is invalid.") from error
            sources = bundle.manifest.sources
            if (bundle.manifest.request_id != request_id or len(sources) != 1 or
                    sources[0].sha256 != secured_brief.sha256 or
                    bundle.requirement_ir.source_manifest[0].kind != secured_brief.kind):
                raise VersionStoreError("validation_failed", "Parse Bundle does not match the Brief.")
            bundle_bytes = bundle.model_dump_json().encode("utf-8")
            if len(bundle_bytes) > _MAX_BUNDLE_BYTES:
                raise VersionStoreError("validation_failed", "Academic parse result is too large.")
            bundle_path.write_bytes(bundle_bytes)
            version = self.store.create_task(
                paper_path, intake=AcademicIntakeInput(
                    request_id=request_id, input_fingerprint=fingerprint,
                    brief_path=brief_path, brief_suffix=brief_suffix,
                    brief_sha256=secured_brief.sha256,
                    bundle_path=bundle_path,
                    bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
                    model_processing_acknowledged=True,
                ),
            )
            if version.docx_sha256 != secured_paper.sha256:
                raise VersionStoreError("validation_failed", "Stored paper differs from upload.")
            return AcademicIntakeResult(version, self.load_bundle(version.task_id), False)
        finally:
            _safe_remove_directory(stage, self.store.staging_dir, self.store.root)

    def load_bundle(self, task_id: str) -> AcademicParseBundle:
        intake = self.store.get_academic_intake(task_id)
        if intake is None:
            raise VersionStoreError("needs_user_input", "Task has no academic parse.")
        try:
            bundle = AcademicParseBundle.model_validate_json(
                intake.bundle_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise VersionStoreError("validation_failed", "Stored academic parse is invalid.") from error
        if (bundle.manifest.request_id != intake.request_id or
                len(bundle.manifest.sources) != 1 or
                bundle.manifest.sources[0].sha256 != intake.brief_sha256):
            raise VersionStoreError("validation_failed", "Stored parse no longer matches the Brief.")
        return bundle
