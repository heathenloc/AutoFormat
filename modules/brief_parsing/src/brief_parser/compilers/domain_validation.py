"""Trusted Domain Pack validator registry and built-in validators."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.enums import Readiness, Severity
from brief_parser.domain.requirement_ir import (
    QualityMetrics,
    Requirement,
    RequirementIR,
    UnresolvedItem,
)
from brief_parser.errors import BriefParserError, ErrorCode


@dataclass(frozen=True, slots=True)
class DomainValidationIssue:
    issue_id: str
    topic: str
    description: str
    severity: Severity
    requirement_id: str | None
    evidence_refs: tuple[str, ...]


type DomainValidator = Callable[[RequirementIR], Sequence[DomainValidationIssue]]


class DomainValidatorRegistry:
    def __init__(self, validators: Mapping[str, DomainValidator]) -> None:
        self._validators = dict(validators)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._validators)

    def validate(
        self,
        pack: DomainPack,
        requirement_ir: RequirementIR,
    ) -> list[DomainValidationIssue]:
        unknown = set(pack.validators) - set(self._validators)
        if unknown:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 引用了未注册的 Validator。",
                details={"unknown_validators": sorted(unknown)},
            )
        issues = self._category_issues(pack, requirement_ir)
        for validator_id in pack.validators:
            issues.extend(self._validators[validator_id](requirement_ir))
        return list({item.issue_id: item for item in issues}.values())

    @classmethod
    def builtins(cls) -> DomainValidatorRegistry:
        return cls(
            {
                "duration_validator": _duration_validator,
                "date_validator": _date_validator,
            }
        )

    @staticmethod
    def _category_issues(
        pack: DomainPack,
        requirement_ir: RequirementIR,
    ) -> list[DomainValidationIssue]:
        known = {item.id.casefold() for item in pack.categories}
        known.update(alias.casefold() for item in pack.categories for alias in item.aliases)
        return [
            _issue(
                "unknown_category",
                requirement,
                "Requirement 类别不在当前 Domain Pack 中，已保留为附加约束。",
                Severity.WARNING,
            )
            for requirement in requirement_ir.requirements
            if requirement.category.casefold() not in known
            and requirement.custom_category is None
        ]


def project_domain_issues(
    requirement_ir: RequirementIR,
    issues: Sequence[DomainValidationIssue],
) -> RequirementIR:
    """Return a new IR whose readiness includes trusted Domain Pack validation."""

    existing = {item.id: item for item in requirement_ir.unresolved_items}
    blocker_count = 0
    warning_count = 0
    for issue in issues:
        if not issue.evidence_refs:
            raise ValueError("domain validation issues require evidence")
        existing[issue.issue_id] = UnresolvedItem(
            id=issue.issue_id,
            topic=issue.topic,
            description=issue.description,
            severity=issue.severity,
            reason_code="domain_pack_validation",
            evidence_refs=list(issue.evidence_refs),
            downstream_policy=(
                "block" if issue.severity == Severity.BLOCKER else "do_not_assume"
            ),
        )
        if issue.severity == Severity.BLOCKER:
            blocker_count += 1
        else:
            warning_count += 1

    readiness = requirement_ir.readiness
    if blocker_count:
        readiness = Readiness.INCOMPLETE
    elif warning_count and readiness == Readiness.COMPLETE:
        readiness = Readiness.USABLE_WITH_WARNINGS

    reason_codes = list(requirement_ir.quality.readiness_reason_codes)
    if blocker_count and "domain_validation_blocker" not in reason_codes:
        reason_codes.append("domain_validation_blocker")
    if warning_count and "domain_validation_warning" not in reason_codes:
        reason_codes.append("domain_validation_warning")
    quality_payload = requirement_ir.quality.model_dump(mode="python")
    quality_payload.update(
        {
            "unresolved_count": len(existing),
            "blocker_count": requirement_ir.quality.blocker_count + blocker_count,
            "readiness_reason_codes": reason_codes,
        }
    )
    payload = requirement_ir.model_dump(mode="python")
    payload.update(
        {
            "readiness": readiness,
            "unresolved_items": list(existing.values()),
            "quality": QualityMetrics.model_validate(quality_payload),
        }
    )
    return RequirementIR.model_validate(payload)


def _duration_validator(requirement_ir: RequirementIR) -> list[DomainValidationIssue]:
    issues: list[DomainValidationIssue] = []
    allowed_units = {"second", "minute", "hour"}
    for requirement in requirement_ir.requirements:
        if requirement.category != "duration" and requirement.value.type != "duration":
            continue
        values = (
            requirement.value.amount
            if isinstance(requirement.value.amount, list)
            else [requirement.value.amount]
        )
        valid_amounts = bool(values) and all(
            isinstance(value, int | float) and not isinstance(value, bool) and value > 0
            for value in values
        )
        if not valid_amounts or requirement.value.unit not in allowed_units:
            issues.append(
                _issue(
                    "duration_invalid",
                    requirement,
                    "时长 Requirement 缺少可执行的正数值或受支持单位。",
                    Severity.BLOCKER,
                )
            )
    return issues


def _date_validator(requirement_ir: RequirementIR) -> list[DomainValidationIssue]:
    issues: list[DomainValidationIssue] = []
    for requirement in requirement_ir.requirements:
        if requirement.category != "deadline" and requirement.value.type != "date":
            continue
        amount = requirement.value.amount
        valid = False
        if isinstance(amount, str):
            try:
                date.fromisoformat(amount)
                valid = True
            except ValueError:
                pass
        if not valid:
            issues.append(
                _issue(
                    "date_invalid",
                    requirement,
                    "日期 Requirement 不是可执行的 ISO 日期。",
                    Severity.BLOCKER,
                )
            )
    return issues


def _issue(
    topic: str,
    requirement: Requirement,
    description: str,
    severity: Severity,
) -> DomainValidationIssue:
    payload = json.dumps(
        {"topic": topic, "requirement_id": requirement.id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return DomainValidationIssue(
        issue_id=f"domain_{sha256(payload.encode()).hexdigest()[:24]}",
        topic=topic,
        description=description,
        severity=severity,
        requirement_id=requirement.id,
        evidence_refs=tuple(requirement.evidence_refs),
    )
