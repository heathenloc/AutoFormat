"""Conservative projection from validated Requirement IR to academic rules.

Source classification is an explicit trusted input. This compiler never infers
that a template observation or an unclassified model candidate is a school rule.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from brief_parser.domain.academic_format import (
    AcademicFormatIssue,
    AcademicFormatRule,
    AcademicFormatRuleSet,
    AcademicTarget,
    AcademicValue,
)
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.enums import (
    DownstreamPolicy,
    EvidenceMatchStatus,
    Modality,
    Operator,
    Readiness,
    VerificationStatus,
)
from brief_parser.domain.requirement_ir import (
    EvidenceReference,
    Requirement,
    RequirementIR,
    SourceManifest,
)

_ALIGNMENT_TERMS = {
    "left": re.compile(r"左对齐|靠左|\bleft(?:[ -]aligned)?\b", re.IGNORECASE),
    "center": re.compile(r"居中|\bcent(?:er|re)(?:ed)?\b", re.IGNORECASE),
    "right": re.compile(r"右对齐|靠右|\bright(?:[ -]aligned)?\b", re.IGNORECASE),
    "both": re.compile(r"两端对齐|\bjustif(?:y|ied)\b", re.IGNORECASE),
}
_NEGATION = re.compile(r"不得|不要|不应|禁止|避免|\bnot\b|\bprohibit(?:ed)?\b", re.IGNORECASE)


class AcademicFormatCompiler:
    """Only an exact, classified body alignment becomes a verified semantic rule."""

    def compile_bundle(
        self,
        bundle: AcademicParseBundle,
        domain_pack: DomainPack,
        *,
        explicit_requirement_ids: Collection[str],
    ) -> AcademicFormatRuleSet:
        """Use the versioned parse-only Bundle as the source of rules and evidence."""
        return self.compile(
            bundle.requirement_ir,
            domain_pack,
            explicit_requirement_ids=explicit_requirement_ids,
        )

    def compile(
        self,
        requirement_ir: RequirementIR,
        domain_pack: DomainPack,
        *,
        explicit_requirement_ids: Collection[str],
    ) -> AcademicFormatRuleSet:
        if (domain_pack.id != "academic_paper"
                or requirement_ir.domain_pack.id != domain_pack.id
                or requirement_ir.domain_pack.version != domain_pack.version):
            raise ValueError("Academic compiler requires the matching academic_paper pack.")
        known_ids = {item.id for item in requirement_ir.requirements}
        if isinstance(explicit_requirement_ids, str):
            raise ValueError("Source classification must be a collection of Requirement IDs.")
        explicit = frozenset(explicit_requirement_ids)
        if not explicit <= known_ids:
            raise ValueError("Source classification names an unknown Requirement.")

        conflicted = {
            item_id for conflict in requirement_ir.conflicts for item_id in conflict.items
        }
        blocked_evidence = {
            evidence_id
            for item in requirement_ir.unresolved_items
            for evidence_id in item.evidence_refs
        }
        sources = {source.source_id: source for source in requirement_ir.source_manifest}
        rules: list[AcademicFormatRule] = []
        issues: list[AcademicFormatIssue] = []
        for requirement in requirement_ir.requirements:
            evidence = [requirement_ir.evidence_index[key] for key in requirement.evidence_refs]
            problem = self._problem(
                requirement_ir, requirement, evidence, sources,
                classified=requirement.id in explicit,
                conflicted=requirement.id in conflicted,
                unresolved=bool(set(requirement.evidence_refs) & blocked_evidence),
            )
            if problem is not None:
                status, reason, next_action = problem
                issues.append(AcademicFormatIssue(
                    source_requirement_id=requirement.id, status=status,
                    reason=reason, next_action=next_action,
                    evidence_ids=list(requirement.evidence_refs),
                ))
                continue
            # _problem guarantees a supported text alignment with one exact token.
            value = requirement.value.amount
            assert isinstance(value, str)
            normalized = _normalize_alignment(value)
            assert normalized is not None
            quote = " ".join(item.quote for item in evidence)
            term = _ALIGNMENT_TERMS[normalized].search(quote)
            assert term is not None
            rules.append(AcademicFormatRule(
                rule_id=f"fmt_{requirement.id}",
                source_requirement_id=requirement.id,
                source_kind="brief_explicit",
                source_artifact_id=requirement_ir.artifact_id,
                source_version=(f"{requirement_ir.artifact_id}:"
                                f"v{requirement_ir.artifact_version}"),
                evidence_refs=evidence,
                target=AcademicTarget(
                    object_kind="paragraph", semantic_role="body", selector="semantic_role"
                ),
                property_id="paragraph.alignment",
                value=AcademicValue(
                    original_text=term.group(), normalized=normalized,
                    unit=None, dictionary_version="academic-alignment/1.0",
                ),
                requested_scope="same_kind", effective_scope="same_kind",
                status="verified",
                reason="Explicit source and one exact alignment value were verified.",
            ))
        return AcademicFormatRuleSet(
            source_artifact_id=requirement_ir.artifact_id,
            source_artifact_version=requirement_ir.artifact_version,
            domain_pack=requirement_ir.domain_pack,
            rules=rules, issues=issues,
        )

    @staticmethod
    def _problem(
        ir: RequirementIR, requirement: Requirement, evidence: list[EvidenceReference],
        sources: dict[str, SourceManifest], *,
        classified: bool, conflicted: bool, unresolved: bool,
    ) -> tuple[str, str, str] | None:
        if ir.readiness == Readiness.INCOMPLETE:
            return ("parse_incomplete", "解析整体未达到可用状态。", "先处理解析失败项。")
        if not classified or requirement.origin != "source":
            return (
                "needs_source_classification", "尚未确认这是 Brief 明文格式要求。",
                "确认来源类型；模板观察和示例不得自动执行。",
            )
        if conflicted:
            return ("pending_conflict", "此要求涉及未处理的冲突。", "先记录用户冲突决定。")
        if requirement.condition is not None:
            return (
                "pending_condition", "适用条件尚未判断。", "确认当前论文适用的提交场景。"
            )
        if unresolved:
            return ("check_only", "同一证据仍有未解决项。", "先核对该证据及范围。")
        if (requirement.verification_status != VerificationStatus.VERIFIED
                or any(item.match_status != EvidenceMatchStatus.EXACT for item in evidence)
                or any(sources[item.source_id].extraction_status != "complete"
                       for item in evidence)):
            return ("evidence_unverified", "要求或原文证据未完全验证。", "核对原文证据。")
        if (requirement.modality != Modality.MUST
                or requirement.operator != Operator.EQ
                or requirement.downstream_policy != DownstreamPolicy.ENFORCE):
            return ("check_only", "要求不是可直接执行的强制等值格式规则。", "人工检查。")
        if (requirement.category != "body_text" or requirement.subject != "body"
                or requirement.scope.applies_to != ["body"]
                or requirement.scope.excludes):
            return ("unsupported", "目标范围不是明确的全部正文段落。", "等待范围规划器支持。")
        value = requirement.value.amount
        if (requirement.value.type != "paragraph_alignment"
                or not isinstance(value, str) or _normalize_alignment(value) is None
                or requirement.value.unit is not None):
            return ("unsupported", "尚不支持此论文格式属性或值。", "保留原文供后续处理。")
        normalized = _normalize_alignment(value)
        assert normalized is not None
        quote = " ".join(item.quote for item in evidence)
        matched = {name for name, pattern in _ALIGNMENT_TERMS.items() if pattern.search(quote)}
        if matched != {normalized} or _NEGATION.search(quote):
            return (
                "value_evidence_mismatch", "规范值不能由唯一且肯定的原文对齐词证明。",
                "核对原文及属性归一结果。",
            )
        return None


def _normalize_alignment(value: str) -> str | None:
    if value in _ALIGNMENT_TERMS:
        return value
    matches = [name for name, pattern in _ALIGNMENT_TERMS.items()
               if pattern.fullmatch(value.strip())]
    return matches[0] if len(matches) == 1 else None
