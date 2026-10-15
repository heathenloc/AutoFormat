"""Read-only evidence check before a PDF selection can reach DOCX anchoring."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .preview import PreviewArtifact, PreviewError, _sha256


def verify_pdf_selection(
    *,
    artifact: PreviewArtifact,
    data_root: Path,
    source_docx: Path,
    selected_text: str,
    pdf_page: int,
) -> None:
    """Check immutable artifact provenance and the selected page's text.

    This is a conservative evidence gate, not a PDF.js text-layer offset mapper.
    The caller must load ``artifact`` and the version path from trusted storage.
    """
    root = data_root.resolve(strict=True)
    source = source_docx.resolve(strict=True)
    if not source.is_relative_to(root) or source_docx.is_symlink():
        raise PreviewError("stale_base_version", "Stored DOCX path is invalid.")
    if _sha256(source) != artifact.source_sha256:
        raise PreviewError("stale_base_version", "Stored DOCX differs from preview source.")

    if (
        artifact.schema_version != "preview-artifact/1.0"
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", artifact.artifact_id)
        or artifact.pdf_relative_path != f"artifacts/previews/{artifact.artifact_id}.pdf"
    ):
        raise PreviewError("stale_preview", "Preview artifact metadata is invalid.")
    pdf = root / artifact.pdf_relative_path
    if pdf.is_symlink() or not pdf.is_file() or not pdf.resolve().is_relative_to(root):
        raise PreviewError("stale_preview", "Preview PDF is unavailable.")
    if _sha256(pdf) != artifact.pdf_sha256:
        raise PreviewError("stale_preview", "Preview PDF hash changed.")
    if not isinstance(pdf_page, int) or pdf_page < 1 or pdf_page > artifact.page_count:
        raise PreviewError("stale_preview", "Selected PDF page is invalid.")
    if not selected_text or len(selected_text) > 4096 or selected_text.isspace():
        raise PreviewError("needs_user_input", "Selected PDF text is empty or too long.")
    if "\n" in selected_text or "\r" in selected_text:
        raise PreviewError("ambiguous_target", "Cross-line selection needs manual targeting.")

    try:
        with pdf.open("rb") as stream:
            reader = PdfReader(stream, strict=True)
            if len(reader.pages) != artifact.page_count:
                raise PreviewError("stale_preview", "Preview PDF page count changed.")
            page_text = reader.pages[pdf_page - 1].extract_text() or ""
    except (PdfReadError, OSError, ValueError) as error:
        raise PreviewError("stale_preview", "Preview PDF cannot be read.") from error

    if page_text.count(selected_text) != 1:
        raise PreviewError(
            "ambiguous_target",
            "Selected text is missing or repeated on the claimed PDF page.",
        )
