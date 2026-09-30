"""Read-only target review between academic rules and DOCX edit operations.

The Word Normal style is only a candidate signal. A same-kind Brief rule cannot
become an executable operation until the document's actual body scope is known.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from brief_parser.domain.academic_format import AcademicFormatRuleSet
from jsonschema import Draft202012Validator, ValidationError

from .preview import _sha256


_SCHEMA = json.loads((Path(__file__).parent / "schemas" /
    "docx-target-index-1.0.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)
_HASH = re.compile(r"^[a-f0-9]{64}$")
_ALIGNMENTS = {"left", "center", "right", "both"}
_ROLE_EVIDENCE = {
    "body_candidate": {"normal_style_only"},
    "heading_candidate": {"built_in_heading_style"},
    "table_cell": {"inside_table"},
    "unclassified": {"empty_paragraph", "complex_or_hidden_content",
                     "numbering_properties", "no_reliable_body_role"},
}


class TargetPlanningError(ValueError):
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        super().__init__(reason)


class DotnetTargetIndexer:
    """Invoke a pinned read-only index binary without a shell or restore."""

    def __init__(self, *, dotnet_path: Path, index_dll: Path,
                 expected_index_sha256: str, timeout_seconds: int = 60) -> None:
        if (not _HASH.fullmatch(expected_index_sha256) or timeout_seconds < 1 or
                dotnet_path.is_symlink() or index_dll.is_symlink()):
            raise TargetPlanningError("validation_failed", "Indexer configuration is invalid.")
        self.dotnet_path = dotnet_path.resolve(strict=True)
        self.index_dll = index_dll.resolve(strict=True)
        if not self.dotnet_path.is_file() or not self.index_dll.is_file():
            raise TargetPlanningError("validation_failed", "Indexer executable is unavailable.")
        self.expected_index_sha256 = expected_index_sha256
        self.timeout_seconds = timeout_seconds

    def inspect(self, docx_path: Path, *, expected_docx_sha256: str) -> dict[str, Any]:
        if not _HASH.fullmatch(expected_docx_sha256) or docx_path.is_symlink():
            raise TargetPlanningError("validation_failed", "DOCX binding is invalid.")
        source = docx_path.resolve(strict=True)
        if (not source.is_file() or _sha256(source) != expected_docx_sha256):
            raise TargetPlanningError("stale_base_version", "DOCX differs from selected version.")
        if _sha256(self.index_dll) != self.expected_index_sha256:
            raise TargetPlanningError("validation_failed", "Indexer executable hash changed.")
        try:
            completed = subprocess.run(
                [str(self.dotnet_path), str(self.index_dll), "inspect", str(source)],
                cwd=source.parent, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TargetPlanningError("validation_failed", "DOCX indexer failed or timed out.") from error
        if completed.returncode != 0 or len(completed.stdout) > 16_777_216:
            raise TargetPlanningError("validation_failed", "DOCX indexer did not return a bounded result.")
        try:
            result = json.loads(completed.stdout)
            validate_target_index(result, expected_docx_sha256=expected_docx_sha256)
        except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as error:
            raise TargetPlanningError("validation_failed", "DOCX indexer returned invalid data.") from error
        if _sha256(source) != expected_docx_sha256:
            raise TargetPlanningError("stale_base_version", "DOCX changed during indexing.")
        return result


def validate_target_index(index: dict[str, Any], *, expected_docx_sha256: str) -> None:
    _VALIDATOR.validate(index)
    if index["sha256"] != expected_docx_sha256:
        raise TargetPlanningError("stale_base_version", "Target index belongs to another DOCX.")
    paragraphs = index["paragraphs"]
    if index["paragraph_count"] != len(paragraphs):
        raise TargetPlanningError("validation_failed", "Target index count is inconsistent.")
    paths: set[str] = set()
    for number, paragraph in enumerate(paragraphs, start=1):
        if paragraph["object_id"] != f"p:{number:06d}" or paragraph["xml_path"] in paths:
            raise TargetPlanningError("validation_failed", "Target index IDs or paths are inconsistent.")
        paths.add(paragraph["xml_path"])
        role = paragraph["role_candidate"]
        evidence = paragraph["role_evidence"]
        if evidence not in _ROLE_EVIDENCE[role]:
            raise TargetPlanningError("validation_failed", "Target role and evidence disagree.")
        if role == "body_candidate" and (paragraph["style_id"] != "Normal" or
                paragraph["is_empty"] or paragraph["requires_manual_targeting"]):
            raise TargetPlanningError("validation_failed", "Body candidate is not structurally eligible.")
        if paragraph["is_empty"] and paragraph["text_preview"]:
            raise TargetPlanningError("validation_failed", "Empty paragraph has a text preview.")


def build_body_alignment_review(
    *, ruleset: AcademicFormatRuleSet, index: dict[str, Any],
    base_version_id: str, expected_base_docx_sha256: str,
    rules_snapshot_id: str,
) -> dict[str, Any]:
    """Create a non-executable review of a global body alignment rule.

    Every paragraph is accounted for. Candidates still need scope confirmation;
    custom styles and ambiguous structure are surfaced instead of skipped.
    """
    if (not base_version_id.strip() or not rules_snapshot_id.strip()
            or not _HASH.fullmatch(expected_base_docx_sha256)):
        raise TargetPlanningError("validation_failed", "Plan version or rules snapshot is missing.")
    validate_target_index(index, expected_docx_sha256=expected_base_docx_sha256)
    reviews = []
    for rule in ruleset.rules:
        supported = (rule.status == "verified" and rule.source_kind == "brief_explicit"
                     and rule.target.object_kind == "paragraph"
                     and rule.target.semantic_role == "body"
                     and rule.target.selector == "semantic_role"
                     and rule.property_id == "paragraph.alignment"
                     and rule.character_scope == "all" and rule.condition is None
                     and rule.requested_scope == "same_kind"
                     and rule.effective_scope == "same_kind"
                     and isinstance(rule.value.normalized, str)
                     and rule.value.normalized in _ALIGNMENTS)
        targets = []
        if supported:
            for paragraph in index["paragraphs"]:
                role = paragraph["role_candidate"]
                disposition = (
                    "blocked_complex_content" if paragraph["requires_manual_targeting"]
                    else "needs_body_confirmation" if role == "body_candidate"
                    else "needs_classification" if role == "unclassified"
                    else "excluded_candidate"
                )
                targets.append({
                    "object_id": paragraph["object_id"],
                    "xml_path": paragraph["xml_path"],
                    "text_sha256": paragraph["text_sha256"],
                    "text_preview": paragraph["text_preview"],
                    "role_candidate": role,
                    "role_evidence": paragraph["role_evidence"],
                    "disposition": disposition,
                })
        reviews.append({
            "rule_id": rule.rule_id,
            "source_requirement_id": rule.source_requirement_id,
            "source_version": rule.source_version,
            "requested_scope": rule.requested_scope,
            "property_id": rule.property_id,
            "value": rule.value.normalized,
            "status": ("needs_user_input" if supported else
                       rule.status if rule.status != "verified" else "unsupported_property"),
            "estimated_affected_count": None,
            "targets": targets,
        })
    return {
        "schema_version": "target-review-plan/1.0",
        "base_version_id": base_version_id,
        "base_docx_sha256": index["sha256"],
        "rules_snapshot_id": rules_snapshot_id,
        "status": "needs_user_input",
        "executable_operations": [],
        "rule_reviews": reviews,
        "source_issues": [{
            "source_requirement_id": issue.source_requirement_id,
            "status": issue.status,
            "reason": issue.reason,
            "next_action": issue.next_action,
        } for issue in ruleset.issues],
    }
