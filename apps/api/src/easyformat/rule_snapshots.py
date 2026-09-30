"""Immutable, task-bound snapshots written only by the trusted parse workflow."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from brief_parser.domain.academic_format import AcademicFormatRuleSet
from pydantic import ValidationError

from .version_store import VersionStore


_ID = re.compile(r"^[a-f0-9]{32}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")


class RuleSnapshotError(ValueError):
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    task_id: str
    base_version_id: str
    snapshot_id: str
    ruleset: AcademicFormatRuleSet


class RuleSnapshotStore:
    """Pins one verified Brief projection to a task until Brief update support exists.

    Registration is an internal method and is deliberately absent from HTTP routes.
    A second, different snapshot cannot silently replace the first one.
    """

    def __init__(self, versions: VersionStore) -> None:
        self.versions = versions
        self.root = versions.root / "rule_snapshots"
        self.root.mkdir(exist_ok=True)
        if (self.root.is_symlink() or
                (hasattr(self.root, "is_junction") and self.root.is_junction()) or
                self.root.resolve().parent != versions.root):
            raise RuleSnapshotError("validation_failed", "Rule snapshot directory is redirected.")

    def _path(self, task_id: str) -> Path:
        if not _ID.fullmatch(task_id):
            raise RuleSnapshotError("validation_failed", "Task ID is invalid.")
        path = self.root / f"{task_id}.json"
        if (path.is_symlink() or
                (hasattr(path, "is_junction") and path.is_junction())):
            raise RuleSnapshotError("validation_failed", "Rule snapshot is redirected.")
        return path

    @staticmethod
    def _canonical_ruleset(ruleset: AcademicFormatRuleSet) -> tuple[AcademicFormatRuleSet, bytes]:
        try:
            validated = AcademicFormatRuleSet.model_validate(ruleset.model_dump(mode="json"))
            encoded = json.dumps(validated.model_dump(mode="json"),
                                 ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (AttributeError, ValidationError, TypeError, ValueError) as error:
            raise RuleSnapshotError("validation_failed", "Academic ruleset is invalid.") from error
        if len(encoded) > 4 * 1024 * 1024:
            raise RuleSnapshotError("validation_failed", "Academic ruleset is too large.")
        return validated, encoded

    def register(
        self, *, task_id: str, base_version_id: str,
        ruleset: AcademicFormatRuleSet,
    ) -> RuleSnapshot:
        base = self.versions.get_version(task_id, base_version_id)
        if base.kind != "original":
            raise RuleSnapshotError("validation_failed", "Rule snapshot must bind to V0.")
        validated, encoded = self._canonical_ruleset(ruleset)
        snapshot_id = hashlib.sha256(encoded).hexdigest()
        path = self._path(task_id)
        if path.exists():
            existing = self.load(task_id)
            if (existing.snapshot_id != snapshot_id or
                    existing.base_version_id != base_version_id):
                raise RuleSnapshotError("blocked_conflict", "Task already has another rule snapshot.")
            return existing
        envelope = {
            "schema_version": "task-rule-snapshot/1.0",
            "task_id": task_id, "base_version_id": base_version_id,
            "snapshot_id": snapshot_id,
            "ruleset": validated.model_dump(mode="json"),
        }
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(envelope, stream, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
                stream.write("\n")
        except FileExistsError:
            return self.register(task_id=task_id, base_version_id=base_version_id,
                                 ruleset=validated)
        return RuleSnapshot(task_id, base_version_id, snapshot_id, validated)

    def load(self, task_id: str) -> RuleSnapshot:
        path = self._path(task_id)
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024 + 4096:
            raise RuleSnapshotError("needs_user_input", "Task has no valid rule snapshot.")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(envelope, dict) or
                    set(envelope) != {"schema_version", "task_id", "base_version_id",
                                      "snapshot_id", "ruleset"} or
                    envelope["schema_version"] != "task-rule-snapshot/1.0" or
                    envelope["task_id"] != task_id or
                    not _ID.fullmatch(envelope["base_version_id"]) or
                    not _HASH.fullmatch(envelope["snapshot_id"])):
                raise ValueError("Envelope is invalid.")
            ruleset, encoded = self._canonical_ruleset(
                AcademicFormatRuleSet.model_validate(envelope["ruleset"]))
            if hashlib.sha256(encoded).hexdigest() != envelope["snapshot_id"]:
                raise ValueError("Ruleset hash changed.")
            base = self.versions.get_version(task_id, envelope["base_version_id"])
            if base.kind != "original":
                raise ValueError("Ruleset base is invalid.")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, ValidationError) as error:
            raise RuleSnapshotError("validation_failed", "Rule snapshot cannot be validated.") from error
        return RuleSnapshot(task_id, envelope["base_version_id"],
                            envelope["snapshot_id"], ruleset)
