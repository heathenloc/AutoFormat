"""Deterministic conflict detection over evidence-backed requirement candidates."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from brief_parser.domain.candidates import (
    CandidateConflict,
    CandidateRequirement,
    ExtractorOutput,
    ResolutionDecision,
)
from brief_parser.domain.enums import Priority, Severity
from brief_parser.domain.foundation import EvidenceIndex

_EXPLICIT_PRECEDENCE = re.compile(
    r"以.+为准|优先(?:采用|使用|执行)?|最新(?:版|版本)|最终(?:版|版本)|"
    r"取代|替代前述|例外|除外|仅当|如果.+则|若.+则|"
    r"\b(?:takes precedence|supersedes?|latest version|final version|exception|only if)\b",
    re.IGNORECASE,
)


class ConflictDetector:
    """Combine explicit disputes with incompatible values for one semantic key."""

    def detect(self, output: ExtractorOutput) -> list[CandidateConflict]:
        conflicts = list(output.candidate_conflicts)
        by_semantic_key: dict[str, list[CandidateRequirement]] = defaultdict(list)
        for requirement in output.requirements:
            by_semantic_key[requirement.semantic_key].append(requirement)

        for semantic_key, requirements in sorted(by_semantic_key.items()):
            signatures = {self._signature(item) for item in requirements}
            if len(requirements) < 2 or len(signatures) < 2:
                continue
            conflicts.append(
                CandidateConflict(
                    topic=semantic_key,
                    severity=(
                        Severity.BLOCKER
                        if any(
                            item.priority in {Priority.CRITICAL, Priority.HIGH}
                            for item in requirements
                        )
                        else Severity.WARNING
                    ),
                    candidate_ids=sorted(item.candidate_id for item in requirements),
                    reason_code="contradictory_values",
                    evidence_refs=sorted(
                        {
                            evidence_id
                            for item in requirements
                            for evidence_id in item.evidence_refs
                        }
                    ),
                )
            )

        unique: dict[tuple[str, ...], CandidateConflict] = {}
        for conflict in conflicts:
            key = tuple(sorted(conflict.candidate_ids))
            current = unique.get(key)
            if current is None or self._severity_rank(conflict.severity) > self._severity_rank(
                current.severity
            ):
                unique[key] = conflict
        return sorted(unique.values(), key=lambda item: (item.topic, item.candidate_ids))

    @staticmethod
    def _signature(requirement: CandidateRequirement) -> str:
        return json.dumps(
            {
                "modality": requirement.modality.value,
                "operator": requirement.operator.value,
                "value": requirement.value.model_dump(mode="json"),
                "scope": requirement.scope.model_dump(mode="json"),
                "condition_text": requirement.condition_text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _severity_rank(severity: Severity) -> int:
        return {
            Severity.INFO: 0,
            Severity.WARNING: 1,
            Severity.BLOCKER: 2,
        }[severity]


class ResolutionEvidencePolicy:
    """Only allow resolution when cited source text states an ordering rule."""

    def is_supported(
        self,
        decision: ResolutionDecision,
        evidence_index: EvidenceIndex,
    ) -> bool:
        if decision.outcome != "resolved":
            return True
        return any(
            _EXPLICIT_PRECEDENCE.search(evidence_index[evidence_id].quote) is not None
            for evidence_id in decision.evidence_refs
        )
