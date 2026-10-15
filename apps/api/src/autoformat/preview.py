"""Replaceable, fail-closed DOCX preview rendering boundary."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

from brief_parser.adapters import FileSecurityValidator
from brief_parser.errors import BriefParserError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PreviewError(Exception):
    """A preview-specific status with no document text in its message."""

    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PreviewArtifact:
    schema_version: str
    artifact_id: str
    source_sha256: str
    pdf_sha256: str
    pdf_relative_path: str
    page_count: int
    selectable_text_chars: int
    renderer_id: str
    renderer_version: str


class PreviewRenderer(Protocol):
    def render(self, source_docx: Path, artifact_id: str) -> PreviewArtifact: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_docx_for_render(source_docx: Path) -> str:
    """Reuse the copied parser's ZIP checks, then reject active or linked content."""
    try:
        secured = FileSecurityValidator().secure_file(
            source_docx, source_id="preview-source", client_source_id="preview-source"
        )
    except BriefParserError as error:
        raise PreviewError("unsafe_input", "DOCX failed file security validation.") from error

    if secured.kind != "docx" or secured.security_warnings:
        raise PreviewError("unsafe_input", "DOCX contains embedded objects or external links.")

    with ZipFile(source_docx) as archive:
        for member in archive.infolist():
            name = member.filename.lower()
            if name.startswith(("word/embeddings/", "word/activex/")) or "afchunk" in name:
                raise PreviewError("unsafe_input", "DOCX contains active or embedded content.")
            if name.endswith(".rels"):
                try:
                    root = ElementTree.fromstring(archive.read(member))
                except ElementTree.ParseError as error:
                    raise PreviewError("unsafe_input", "DOCX relationships cannot be read.") from error
                if any(
                    element.attrib.get("TargetMode", "").lower() == "external"
                    for element in root.iter()
                ):
                    raise PreviewError("unsafe_input", "DOCX has an external relationship.")

        field_parts: list[str] = []
        for member in archive.infolist():
            name = member.filename.lower()
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            try:
                xml = ElementTree.fromstring(archive.read(member))
            except ElementTree.ParseError as error:
                raise PreviewError("unsafe_input", "DOCX Word XML cannot be read.") from error
            for element in xml.iter():
                local_name = element.tag.rsplit("}", 1)[-1]
                if local_name == "altChunk":
                    raise PreviewError("unsafe_input", "DOCX contains imported external content.")
                if local_name == "instrText":
                    field_parts.append(element.text or "")
                elif local_name == "fldSimple":
                    field_parts.extend(
                        value for key, value in element.attrib.items()
                        if key.rsplit("}", 1)[-1] == "instr"
                    )
        instructions = "".join(field_parts).upper()
        if any(token in instructions for token in
               ("INCLUDETEXT", "INCLUDEPICTURE", "DDEAUTO", "DDE ", "DATABASE", "LINK ")):
            raise PreviewError("unsafe_input", "DOCX contains an external-content field.")

    return secured.sha256


class LibreOfficeRenderer:
    """Headless converter with explicit binary, bounded work, and isolated profile."""

    def __init__(
        self,
        *,
        soffice_path: Path,
        expected_soffice_sha256: str,
        data_root: Path,
        timeout_seconds: int = 120,
        max_pdf_bytes: int = 100 * 1024 * 1024,
        max_pdf_pages: int = 500,
    ) -> None:
        if soffice_path.is_symlink() or data_root.is_symlink():
            raise PreviewError("render_failed", "LibreOffice or data directory is redirected.")
        self.soffice_path = soffice_path.resolve(strict=True)
        self.data_root = data_root.resolve(strict=True)
        if not self.soffice_path.is_file():
            raise PreviewError("render_failed", "LibreOffice executable is unavailable.")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_soffice_sha256):
            raise ValueError("Expected LibreOffice executable hash must be SHA-256.")
        self.expected_soffice_sha256 = expected_soffice_sha256.lower()
        if _sha256(self.soffice_path) != self.expected_soffice_sha256:
            raise PreviewError("render_failed", "LibreOffice executable hash changed.")
        if timeout_seconds < 1 or max_pdf_bytes < 1 or max_pdf_pages < 1:
            raise ValueError("Preview limits must be positive.")
        self.timeout_seconds = timeout_seconds
        self.max_pdf_bytes = max_pdf_bytes
        self.max_pdf_pages = max_pdf_pages
        self._renderer_version: str | None = None

    def render(self, source_docx: Path, artifact_id: str) -> PreviewArtifact:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", artifact_id):
            raise PreviewError("render_failed", "Preview artifact ID is invalid.")
        source = source_docx.resolve(strict=True)
        if not source.is_relative_to(self.data_root) or source_docx.is_symlink():
            raise PreviewError("unsafe_input", "DOCX must be a stored task artifact.")
        if _sha256(self.soffice_path) != self.expected_soffice_sha256:
            raise PreviewError("render_failed", "LibreOffice executable changed.")

        source_hash = inspect_docx_for_render(source)
        version = self._get_version()
        artifact_parent = self.data_root / "artifacts"
        if artifact_parent.exists() and not artifact_parent.resolve().is_relative_to(self.data_root):
            raise PreviewError("render_failed", "Preview artifact directory is redirected.")
        artifact_dir = artifact_parent / "previews"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if not artifact_dir.resolve().is_relative_to(self.data_root):
            raise PreviewError("render_failed", "Preview artifact directory is redirected.")
        final_pdf = artifact_dir / f"{artifact_id}.pdf"
        if final_pdf.exists():
            raise PreviewError("render_failed", "Preview artifact already exists.")

        work_root = self.data_root / "preview-work"
        work_root.mkdir(parents=True, exist_ok=True)
        if not work_root.resolve().is_relative_to(self.data_root):
            raise PreviewError("render_failed", "Preview work directory is redirected.")
        work_dir = work_root / uuid4().hex
        work_dir.mkdir()
        output_dir = work_dir / "output"
        output_dir.mkdir()
        profile_dir = work_dir / "profile"
        try:
            render_input = work_dir / "input.docx"
            shutil.copyfile(source, render_input)
            if _sha256(render_input) != source_hash:
                raise PreviewError("unsafe_input", "DOCX changed before preview conversion.")
            if inspect_docx_for_render(render_input) != source_hash:
                raise PreviewError("unsafe_input", "DOCX changed before preview conversion.")
            command = [
                str(self.soffice_path),
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless", "--nodefault", "--norestore", "--nofirststartwizard",
                "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", str(output_dir), str(render_input),
            ]
            environment = os.environ.copy()
            environment["TEMP"] = str(work_dir)
            environment["TMP"] = str(work_dir)
            completed = _run_bounded(command, cwd=work_dir, environment=environment,
                                     timeout_seconds=self.timeout_seconds)

            pdf = output_dir / "input.pdf"
            if completed.returncode != 0 or not pdf.is_file():
                raise PreviewError(
                    "render_failed",
                    f"LibreOffice did not create a PDF (process exit {completed.returncode}).",
                )
            if pdf.stat().st_size > self.max_pdf_bytes:
                raise PreviewError("render_failed", "Preview PDF exceeds configured size limit.")
            try:
                with pdf.open("rb") as stream:
                    reader = PdfReader(stream, strict=True)
                    page_count = len(reader.pages)
                    if page_count > self.max_pdf_pages:
                        raise PreviewError("render_failed", "Preview PDF exceeds configured page limit.")
                    text_chars = sum(len(page.extract_text() or "") for page in reader.pages)
            except (PdfReadError, OSError, ValueError) as error:
                raise PreviewError("render_failed", "Generated PDF cannot be validated.") from error
            if page_count < 1 or text_chars < 1:
                raise PreviewError("render_failed", "Preview PDF has no selectable text.")
            if _sha256(source) != source_hash:
                raise PreviewError("render_failed", "Source DOCX changed during conversion.")

            pdf_hash = _sha256(pdf)
            pdf.rename(final_pdf)
            return PreviewArtifact(
                schema_version="preview-artifact/1.0", artifact_id=artifact_id,
                source_sha256=source_hash, pdf_sha256=pdf_hash,
                pdf_relative_path=final_pdf.relative_to(self.data_root).as_posix(),
                page_count=page_count, selectable_text_chars=text_chars,
                renderer_id="libreoffice", renderer_version=version,
            )
        finally:
            # Never recursively clean a path unless it still resolves inside our work root.
            for delay in (0, 0.25, 0.5, 1, 2, 4, 8):
                if not work_dir.exists() or work_dir.resolve().parent != work_root.resolve():
                    break
                time.sleep(delay)
                try:
                    resolved_work = work_dir.resolve()
                    cleanup_path = _extended_windows_path(resolved_work) if os.name == "nt" else resolved_work
                    shutil.rmtree(cleanup_path)
                    break
                except OSError:
                    # LibreOffice may finish writing its isolated profile after the
                    # console launcher exits. Leave an ignored work dir for recovery
                    # if bounded cleanup attempts cannot remove it.
                    pass

    def _get_version(self) -> str:
        if self._renderer_version is None:
            probe_profile = self.data_root / "preview-probe-profile"
            completed = _run_bounded(
                [str(self.soffice_path), f"-env:UserInstallation={probe_profile.as_uri()}",
                 "--headless", "--version"],
                cwd=self.data_root, environment=os.environ.copy(), timeout_seconds=15,
            )
            version = completed.stdout.strip()
            if completed.returncode != 0 or not version.startswith("LibreOffice "):
                raise PreviewError("render_failed", "LibreOffice version probe failed.")
            self._renderer_version = version
        return self._renderer_version


def _extended_windows_path(path: Path) -> str:
    resolved = str(path)
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def _run_bounded(
    command: list[str], *, cwd: Path, environment: dict[str, str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        if os.name == "nt":
            taskkill = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "taskkill.exe"
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, timeout=10, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise PreviewError("render_failed", "LibreOffice operation timed out.") from error
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
