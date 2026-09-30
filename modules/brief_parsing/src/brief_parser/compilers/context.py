"""Task-specific Context Compiler for downstream model inputs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from brief_parser.compilers.domain_validation import (
    DomainValidationIssue,
    DomainValidatorRegistry,
)
from brief_parser.domain.domain_pack import DomainCategory, DomainPack
from brief_parser.domain.enums import (
    DownstreamPolicy,
    ExecutionReadiness,
    Modality,
    Priority,
    Readiness,
    Severity,
    VerificationStatus,
)
from brief_parser.domain.execution_brief import (
    ExecutionBrief,
    ExecutionConstraint,
    ExecutionItem,
    ExecutionUnresolved,
)
from brief_parser.domain.requirement_ir import (
    Conflict,
    Requirement,
    RequirementIR,
    UnresolvedItem,
)
from brief_parser.errors import BriefParserError, ErrorCode

_META_INSTRUCTION = re.compile(
    r"忽略(?:此前|之前|以上|系统)?(?:指令|规则|提示)|系统提示|访问(?:网页|网络)|"
    r"执行(?:命令|代码)|\bignore\b.{0,32}\b(?:instruction|prompt|rule)s?\b|"
    r"\bsystem prompt\b|\b(?:execute|run)\b.{0,20}\b(?:command|code)\b|"
    r"\baccess\b.{0,20}\b(?:web|internet|network)\b",
    re.IGNORECASE,
)

type TaskCompiler = Callable[
    [RequirementIR, DomainPack, Sequence[DomainValidationIssue]], ExecutionBrief
]


class CompilerRegistry:
    def __init__(self, compilers: Mapping[str, TaskCompiler]) -> None:
        self._compilers = dict(compilers)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._compilers)

    def get(self, compiler_id: str) -> TaskCompiler:
        try:
            return self._compilers[compiler_id]
        except KeyError as exc:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 引用了未注册的 Compiler。",
                details={"unknown_compiler": compiler_id},
            ) from exc

    @classmethod
    def builtins(cls) -> CompilerRegistry:
        return cls({"write_ad_script": _compile_write_ad_script})


class ContextCompiler:
    def __init__(
        self,
        *,
        validators: DomainValidatorRegistry | None = None,
        compilers: CompilerRegistry | None = None,
    ) -> None:
        self._validators = validators or DomainValidatorRegistry.builtins()
        self._compilers = compilers or CompilerRegistry.builtins()

    @property
    def validator_ids(self) -> frozenset[str]:
        return self._validators.ids

    @property
    def compiler_ids(self) -> frozenset[str]:
        return self._compilers.ids

    def compile(
        self,
        requirement_ir: RequirementIR,
        domain_pack: DomainPack,
        *,
        task_type: str,
        domain_issues: Sequence[DomainValidationIssue] | None = None,
    ) -> ExecutionBrief:
        if (
            requirement_ir.domain_pack.id != domain_pack.id
            or requirement_ir.domain_pack.version != domain_pack.version
        ):
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Requirement IR 与 Domain Pack 版本不匹配。",
            )
        if task_type not in domain_pack.compilers:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 不支持请求的任务 Compiler。",
                details={"task_type": task_type},
            )
        issues = (
            self._validators.validate(domain_pack, requirement_ir)
            if domain_issues is None
            else list(domain_issues)
        )
        return self._compilers.get(task_type)(requirement_ir, domain_pack, issues)

    def validate_domain(
        self,
        requirement_ir: RequirementIR,
        domain_pack: DomainPack,
    ) -> list[DomainValidationIssue]:
        return self._validators.validate(domain_pack, requirement_ir)


def _compile_write_ad_script(
    requirement_ir: RequirementIR,
    domain_pack: DomainPack,
    domain_issues: Sequence[DomainValidationIssue],
) -> ExecutionBrief:
    unresolved: list[ExecutionUnresolved] = []
    filtered_meta = False
    for unresolved_item in requirement_ir.unresolved_items:
        if _contains_meta_instruction(unresolved_item.topic, unresolved_item.description):
            unresolved.append(
                _meta_unresolved(unresolved_item.id, unresolved_item.evidence_refs)
            )
            filtered_meta = True
        else:
            unresolved.append(_execution_unresolved(unresolved_item))
    selected, conflict_unresolved = _conflict_selection(requirement_ir)
    unresolved.extend(conflict_unresolved)
    conflicted_ids = {
        item_id
        for conflict in requirement_ir.conflicts
        for item_id in conflict.items
    }
    inactive_conflicted_ids = conflicted_ids - selected
    domain_blocked_requirement_ids = {
        item.requirement_id
        for item in domain_issues
        if item.severity == Severity.BLOCKER and item.requirement_id is not None
    }
    active_domain_issues = [
        domain_issue
        for domain_issue in domain_issues
        if domain_issue.requirement_id is None
        or domain_issue.requirement_id not in inactive_conflicted_ids
    ]
    unresolved.extend(_domain_unresolved(domain_issue) for domain_issue in active_domain_issues)

    objectives: list[ExecutionItem] = []
    for objective in requirement_ir.objectives:
        if _contains_meta_instruction(objective.label, objective.value):
            unresolved.append(_meta_unresolved(objective.id, objective.evidence_refs))
            filtered_meta = True
            continue
        objectives.append(
            ExecutionItem(
                id=f"exec_{objective.id}",
                label=objective.label,
                value=objective.value,
                evidence_refs=objective.evidence_refs,
            )
        )

    facts: dict[str, object] = {}
    for fact in requirement_ir.facts:
        if _contains_meta_instruction(fact.label, fact.value):
            unresolved.append(_meta_unresolved(fact.id, fact.evidence_refs))
            filtered_meta = True
            continue
        key = fact.label if fact.label not in facts else f"{fact.label}#{fact.id}"
        facts[key] = {
            "value": fact.value,
            "evidence_refs": fact.evidence_refs,
            "source_item_id": fact.id,
        }

    references: list[ExecutionItem] = []
    for reference in requirement_ir.references:
        if _contains_meta_instruction(reference.label, reference.value):
            unresolved.append(_meta_unresolved(reference.id, reference.evidence_refs))
            filtered_meta = True
            continue
        references.append(
            ExecutionItem(
                id=f"exec_{reference.id}",
                label=reference.label,
                value={"relation": reference.relation, "value": reference.value},
                evidence_refs=reference.evidence_refs,
            )
        )

    deliverables: list[ExecutionConstraint] = []
    hard_constraints: list[ExecutionConstraint] = []
    prohibitions: list[ExecutionConstraint] = []
    preferences: list[ExecutionConstraint] = []
    additional_constraints: list[ExecutionConstraint] = []
    category_by_name = _category_lookup(domain_pack)
    for requirement in requirement_ir.requirements:
        if requirement.id in conflicted_ids and requirement.id not in selected:
            continue
        if requirement.id in domain_blocked_requirement_ids:
            continue
        if _contains_meta_instruction(requirement.label, requirement.value.amount):
            unresolved.append(_meta_unresolved(requirement.id, requirement.evidence_refs))
            filtered_meta = True
            continue
        if requirement.verification_status not in {
            VerificationStatus.VERIFIED,
            VerificationStatus.VERIFIED_WITH_WARNING,
        }:
            unresolved.append(_invalid_requirement(requirement))
            continue
        category = category_by_name.get(requirement.category.casefold())
        constraint = _constraint(requirement, category)
        canonical_category = category.id if category is not None else requirement.category
        if requirement.modality == Modality.MUST_NOT:
            prohibitions.append(constraint)
        elif requirement.modality == Modality.MUST:
            target = deliverables if canonical_category == "deliverable" else hard_constraints
            target.append(constraint)
        elif requirement.modality in {Modality.SHOULD, Modality.MAY}:
            preferences.append(constraint)
        else:
            additional_constraints.append(constraint)

    unresolved = list({item.id: item for item in unresolved}.values())
    readiness = _execution_readiness(
        requirement_ir,
        unresolved,
        active_domain_issues,
        filtered_meta=filtered_meta,
    )
    return ExecutionBrief(
        task_type="write_ad_script",
        source_artifact_id=requirement_ir.artifact_id,
        source_artifact_version=requirement_ir.artifact_version,
        readiness=readiness,
        locale=requirement_ir.locale,
        objective=objectives,
        facts=facts,
        deliverables=deliverables,
        hard_constraints=hard_constraints,
        prohibitions=prohibitions,
        preferences=preferences,
        references=references,
        additional_constraints=additional_constraints,
        unresolved=unresolved,
    )


def _constraint(
    requirement: Requirement,
    category: DomainCategory | None,
) -> ExecutionConstraint:
    priority = _max_priority(
        requirement.priority,
        category.risk if category is not None else Priority.NORMAL,
    )
    return ExecutionConstraint(
        id=f"exec_{requirement.id}",
        label=requirement.label,
        value={
            "category": category.id if category is not None else requirement.category,
            "operator": requirement.operator.value,
            "value": requirement.value.model_dump(mode="json"),
            "scope": requirement.scope.model_dump(mode="json"),
        },
        evidence_refs=requirement.evidence_refs,
        source_requirement_id=requirement.id,
        priority=priority,
        condition=(
            requirement.condition.expression if requirement.condition is not None else None
        ),
        downstream_policy=requirement.downstream_policy,
    )


def _conflict_selection(
    requirement_ir: RequirementIR,
) -> tuple[set[str], list[ExecutionUnresolved]]:
    selected: set[str] = set()
    unresolved: list[ExecutionUnresolved] = []
    requirement_by_id = {item.id: item for item in requirement_ir.requirements}
    for conflict in requirement_ir.conflicts:
        resolved = _parse_resolution(conflict)
        if resolved is not None:
            selected.update(resolved)
            continue
        evidence_refs = sorted(
            {
                evidence_id
                for item_id in conflict.items
                for evidence_id in requirement_by_id[item_id].evidence_refs
            }
        )
        unresolved.append(
            ExecutionUnresolved(
                id=f"exec_{conflict.id}",
                topic=conflict.topic,
                description="存在未解决的互斥 Requirement，Context Compiler 未选择任一值。",
                evidence_refs=evidence_refs,
                downstream_policy=(
                    "block"
                    if conflict.severity == Severity.BLOCKER
                    or conflict.downstream_policy == DownstreamPolicy.BLOCK
                    else "do_not_assume"
                ),
            )
        )
    return selected, unresolved


def _parse_resolution(conflict: Conflict) -> set[str] | None:
    if conflict.resolution is None or not conflict.resolution.startswith("selected:"):
        return None
    selected = set(filter(None, conflict.resolution.removeprefix("selected:").split(",")))
    return selected if selected and selected <= set(conflict.items) else None


def _execution_unresolved(item: UnresolvedItem) -> ExecutionUnresolved:
    return ExecutionUnresolved(
        id=f"exec_{item.id}",
        topic=item.topic,
        description=item.description,
        evidence_refs=item.evidence_refs,
        downstream_policy=item.downstream_policy,
    )


def _domain_unresolved(issue: DomainValidationIssue) -> ExecutionUnresolved:
    return ExecutionUnresolved(
        id=f"exec_{issue.issue_id}",
        topic=issue.topic,
        description=issue.description,
        evidence_refs=list(issue.evidence_refs),
        downstream_policy=(
            "block" if issue.severity == Severity.BLOCKER else "do_not_assume"
        ),
    )


def _invalid_requirement(requirement: Requirement) -> ExecutionUnresolved:
    return ExecutionUnresolved(
        id=f"exec_invalid_{requirement.id}",
        topic="invalid_requirement",
        description="Requirement 未通过确定性验证，未作为执行约束传播。",
        evidence_refs=requirement.evidence_refs,
        downstream_policy=(
            "block"
            if requirement.priority == Priority.CRITICAL
            or requirement.downstream_policy == DownstreamPolicy.BLOCK
            else "do_not_assume"
        ),
    )


def _meta_unresolved(item_id: str, evidence_refs: Sequence[str]) -> ExecutionUnresolved:
    return ExecutionUnresolved(
        id=f"exec_meta_{item_id}",
        topic="document_meta_instruction",
        description="检测到文档级元指令，该内容未传播给下游模型。",
        evidence_refs=list(evidence_refs),
        downstream_policy="do_not_assume",
    )


def _execution_readiness(
    requirement_ir: RequirementIR,
    unresolved: Sequence[ExecutionUnresolved],
    domain_issues: Sequence[DomainValidationIssue],
    *,
    filtered_meta: bool,
) -> ExecutionReadiness:
    if requirement_ir.readiness == Readiness.INCOMPLETE:
        return ExecutionReadiness.BLOCKED
    if any(item.downstream_policy == "block" for item in unresolved):
        return ExecutionReadiness.BLOCKED
    if any(item.severity == Severity.BLOCKER for item in domain_issues):
        return ExecutionReadiness.BLOCKED
    if (
        requirement_ir.readiness == Readiness.USABLE_WITH_WARNINGS
        or unresolved
        or domain_issues
        or filtered_meta
    ):
        return ExecutionReadiness.READY_WITH_WARNINGS
    return ExecutionReadiness.READY


def _category_lookup(pack: DomainPack) -> dict[str, DomainCategory]:
    result: dict[str, DomainCategory] = {}
    for category in pack.categories:
        result[category.id.casefold()] = category
        result.update(dict.fromkeys((item.casefold() for item in category.aliases), category))
    return result


def _contains_meta_instruction(label: str, value: object) -> bool:
    payload = f"{label}\n{json.dumps(value, ensure_ascii=False, default=str)}"
    return _META_INSTRUCTION.search(payload) is not None


def _max_priority(left: Priority, right: Priority) -> Priority:
    ranks = {
        Priority.LOW: 0,
        Priority.NORMAL: 1,
        Priority.HIGH: 2,
        Priority.CRITICAL: 3,
    }
    return left if ranks[left] >= ranks[right] else right
