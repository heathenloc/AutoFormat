"""Deterministic assembly of validated candidates into Requirement IR v1."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from brief_parser.domain.candidates import (
    CandidateConflict,
    CandidateItem,
    CandidateReference,
    CandidateRequirement,
    CandidateUnresolved,
    CandidateValue,
    ExtractorOutput,
    ResolutionDecision,
)
from brief_parser.domain.enums import (
    DownstreamPolicy,
    EvidenceMatchStatus,
    Priority,
    Severity,
    VerificationStatus,
)
from brief_parser.domain.foundation import (
    ClauseSegmentation,
    CoverageClassification,
    CoverageLedger,
    DeterministicClauseAnalysis,
    EvidenceIndex,
    NumericMention,
)
from brief_parser.domain.pipeline import ProviderCallRecord
from brief_parser.domain.requirement_ir import (
    Conflict,
    DomainPackRef,
    EvidenceBackedItem,
    PipelineInfo,
    QualityMetrics,
    ReferenceItem,
    Requirement,
    RequirementCondition,
    RequirementIR,
    RequirementScope,
    RequirementValue,
    SourceManifest,
    UnclassifiedContent,
    UnresolvedItem,
)
from brief_parser.validators.readiness import ReadinessPolicy

SourceQuality = Literal["complete", "degraded", "failed"]


class RequirementIRAssembler:
    """Own all stable IDs, deterministic verification, quality, and readiness."""

    def __init__(self, *, readiness_policy: ReadinessPolicy | None = None) -> None:
        self._readiness_policy = readiness_policy or ReadinessPolicy()

    def assemble(
        self,
        *,
        request_id: str,
        artifact_id: str,
        artifact_version: int,
        created_at: datetime,
        locale: str,
        domain_pack: DomainPackRef,
        pipeline_info: PipelineInfo,
        source_manifests: Sequence[SourceManifest],
        source_quality: Mapping[str, SourceQuality],
        segmentation: ClauseSegmentation,
        evidence_index: EvidenceIndex,
        analyses: Sequence[DeterministicClauseAnalysis],
        extractor_output: ExtractorOutput,
        conflicts: Sequence[CandidateConflict],
        resolutions: Mapping[str, ResolutionDecision],
        coverage: CoverageLedger,
        provider_calls: Sequence[ProviderCallRecord],
        provider_unverifiable: bool,
        job_token_budget_exceeded: bool = False,
    ) -> RequirementIR:
        analysis_by_evidence = self._analysis_by_evidence(segmentation, analyses)

        facts = [self._evidence_item("fact", item) for item in extractor_output.facts]
        objectives = [
            self._evidence_item("objective", item) for item in extractor_output.objectives
        ]
        references = [self._reference(item) for item in extractor_output.references]

        requirements: list[Requirement] = []
        requirement_id_by_candidate: dict[str, str] = {}
        numeric_results: dict[str, bool] = {}
        for candidate in extractor_output.requirements:
            requirement, numeric_valid, _evidence_valid = self._requirement(
                candidate,
                evidence_index,
                analysis_by_evidence,
            )
            requirements.append(requirement)
            requirement_id_by_candidate[candidate.candidate_id] = requirement.id
            if candidate.value.amount is not None:
                numeric_results[requirement.id] = numeric_valid

        unresolved = [self._unresolved(item) for item in extractor_output.unresolved_items]
        unresolved.extend(
            self._audit_gaps(coverage, segmentation, extractor_output)
        )
        unresolved.extend(
            self._duration_gaps(coverage, segmentation, analyses, extractor_output)
        )
        unresolved = list({item.id: item for item in unresolved}.values())

        final_conflicts = [
            self._conflict(item, requirement_id_by_candidate, resolutions)
            for item in conflicts
        ]
        unclassified = self._unclassified(coverage, segmentation)

        critical = [item for item in requirements if item.priority == Priority.CRITICAL]
        verified_critical = [
            item
            for item in critical
            if item.verification_status == VerificationStatus.VERIFIED
        ]
        critical_unresolved = [
            item
            for item in unresolved
            if item.downstream_policy == "block" or item.severity == Severity.BLOCKER
        ]
        noncritical_unresolved = [
            item for item in unresolved if item not in critical_unresolved
        ]
        blocker_conflicts = [
            item
            for item in final_conflicts
            if item.severity == Severity.BLOCKER and item.resolution is None
        ]
        invalid_evidence_ids = {
            evidence_id
            for evidence_id, evidence in evidence_index.items()
            if evidence.match_status == EvidenceMatchStatus.INVALID
        }
        critical_invalid_evidence = sum(
            bool(set(item.evidence_refs) & invalid_evidence_ids) for item in critical
        )
        critical_invalid_numeric = sum(
            item.id in numeric_results and not numeric_results[item.id] for item in critical
        )
        non_machine_checkable = sum(
            item.machine_checkability
            in {"none", "human_review", "non_machine_checkable", "not_machine_checkable"}
            for item in requirements
        )
        source_incomplete_count = sum(
            item.extraction_status != "complete" for item in source_manifests
        )
        pipeline_warning_count = sum(bool(item.warnings) for item in source_manifests)
        signals = self._readiness_policy.signals_from_ledger(
            coverage,
            critical_requirement_count=len(critical),
            verified_critical_requirement_count=len(verified_critical),
            critical_unresolved_count=len(critical_unresolved),
            noncritical_unresolved_count=len(noncritical_unresolved),
            blocker_count=len(blocker_conflicts),
            source_incomplete_count=source_incomplete_count,
            invalid_evidence_count=len(invalid_evidence_ids),
            critical_invalid_evidence_count=critical_invalid_evidence,
            invalid_numeric_count=sum(not valid for valid in numeric_results.values()),
            critical_invalid_numeric_count=critical_invalid_numeric,
            non_machine_checkable_count=non_machine_checkable,
            pipeline_warning_count=pipeline_warning_count,
            job_token_budget_exceeded=job_token_budget_exceeded,
            provider_unverifiable=provider_unverifiable,
        )
        assessment = self._readiness_policy.evaluate(signals)

        exact_evidence_count = sum(
            item.match_status == EvidenceMatchStatus.EXACT
            for item in evidence_index.values()
        )
        numeric_valid_count = sum(numeric_results.values())
        quality = QualityMetrics(
            source_extraction_quality=dict(source_quality),
            clause_count=coverage.clause_count,
            classified_clause_count=coverage.classified_clause_count,
            unclassified_clause_count=coverage.unclassified_clause_count,
            coverage_ratio=coverage.coverage_ratio,
            evidence_validity_ratio=(
                exact_evidence_count / len(evidence_index) if evidence_index else 0.0
            ),
            numeric_validation_ratio=(
                numeric_valid_count / len(numeric_results) if numeric_results else 1.0
            ),
            conflict_count=len(final_conflicts),
            unresolved_count=len(unresolved),
            blocker_count=len(blocker_conflicts) + len(critical_unresolved),
            provider_call_count=len(provider_calls),
            input_tokens=sum(item.input_tokens for item in provider_calls),
            output_tokens=sum(item.output_tokens for item in provider_calls),
            latency_ms=sum(item.latency_ms for item in provider_calls),
            readiness_reason_codes=[item.value for item in assessment.reason_codes],
        )
        return RequirementIR(
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            request_id=request_id,
            created_at=created_at,
            readiness=assessment.readiness,
            locale=locale,
            domain_pack=domain_pack,
            pipeline=pipeline_info,
            source_manifest=list(source_manifests),
            facts=facts,
            objectives=objectives,
            requirements=requirements,
            references=references,
            conflicts=final_conflicts,
            unresolved_items=unresolved,
            unclassified_content=unclassified,
            evidence_index=dict(evidence_index),
            quality=quality,
        )

    @classmethod
    def dispute_id(cls, conflict: CandidateConflict) -> str:
        return cls._stable_id(
            "disp",
            {
                "topic": conflict.topic,
                "candidate_ids": sorted(conflict.candidate_ids),
                "reason_code": conflict.reason_code,
            },
        )

    @classmethod
    def _evidence_item(cls, kind: str, candidate: CandidateItem) -> EvidenceBackedItem:
        return EvidenceBackedItem(
            id=cls._stable_id(kind, candidate.model_dump(mode="json")),
            label=candidate.label,
            value=candidate.value.model_dump(mode="json"),
            verification_status=VerificationStatus.VERIFIED,
            verification_basis=["evidence_exact_match", "schema_validated"],
            evidence_refs=candidate.evidence_refs,
        )

    @classmethod
    def _reference(cls, candidate: CandidateReference) -> ReferenceItem:
        return ReferenceItem(
            id=cls._stable_id("ref", candidate.model_dump(mode="json")),
            label=candidate.label,
            value=candidate.value.model_dump(mode="json"),
            verification_status=VerificationStatus.VERIFIED,
            verification_basis=["evidence_exact_match", "schema_validated"],
            evidence_refs=candidate.evidence_refs,
            relation=candidate.relation,
        )

    @classmethod
    def _requirement(
        cls,
        candidate: CandidateRequirement,
        evidence_index: EvidenceIndex,
        analysis_by_evidence: Mapping[str, DeterministicClauseAnalysis],
    ) -> tuple[Requirement, bool, bool]:
        evidence_valid = all(
            evidence_index[item].match_status == EvidenceMatchStatus.EXACT
            for item in candidate.evidence_refs
        )
        numeric_valid = True
        basis = ["schema_validated"]
        if evidence_valid:
            basis.insert(0, "evidence_exact_match")

        analyses = [analysis_by_evidence[item] for item in candidate.evidence_refs]
        if candidate.value.amount is not None:
            numeric_valid = any(
                cls._numeric_matches(candidate, mention)
                for analysis in analyses
                for mention in analysis.numeric_mentions
            )
            if numeric_valid:
                basis.append("numeric_rule_match")

        modalities = {
            mention.modality
            for analysis in analyses
            for mention in analysis.modality_mentions
        }
        modality_valid = not modalities or candidate.modality in modalities
        if modalities and modality_valid:
            basis.append("modality_rule_match")

        status = (
            VerificationStatus.VERIFIED
            if evidence_valid and numeric_valid and modality_valid
            else VerificationStatus.INVALID
        )
        condition = None
        if candidate.condition_text is not None:
            condition = RequirementCondition(
                expression=candidate.condition_text,
                evidence_refs=candidate.condition_evidence_refs,
            )
        requirement = Requirement(
            id=cls._stable_id("req", candidate.model_dump(mode="json")),
            semantic_key=candidate.semantic_key,
            category=candidate.category,
            custom_category=candidate.custom_category,
            label=candidate.label,
            subject=candidate.subject,
            modality=candidate.modality,
            operator=candidate.operator,
            value=RequirementValue(
                type=candidate.value.type,
                amount=cls._value_amount(candidate.value),
                unit=candidate.value.unit,
            ),
            scope=RequirementScope(
                applies_to=candidate.scope.applies_to,
                excludes=candidate.scope.excludes,
            ),
            condition=condition,
            priority=candidate.priority,
            machine_checkability=candidate.machine_checkability,
            verification_status=status,
            verification_basis=basis,
            evidence_refs=candidate.evidence_refs,
            downstream_policy=candidate.downstream_policy,
        )
        return requirement, numeric_valid, evidence_valid

    @staticmethod
    def _numeric_matches(candidate: CandidateRequirement, mention: NumericMention) -> bool:
        if Decimal(str(candidate.value.amount)) != mention.amount:
            return False
        candidate_end = candidate.value.range_end
        if (
            None if candidate_end is None else Decimal(str(candidate_end))
        ) != mention.range_end:
            return False
        if candidate.value.unit != mention.unit:
            return False
        return mention.operator is None or candidate.operator == mention.operator

    @staticmethod
    def _value_amount(value: CandidateValue) -> str | float | list[str] | list[float]:
        if value.items:
            return value.items
        if value.amount is not None and value.range_end is not None:
            return [value.amount, value.range_end]
        if value.amount is not None:
            return value.amount
        assert value.text is not None
        return value.text

    @classmethod
    def _unresolved(cls, candidate: CandidateUnresolved) -> UnresolvedItem:
        return UnresolvedItem(
            id=cls._stable_id("unresolved", candidate.model_dump(mode="json")),
            topic=candidate.topic,
            description=candidate.description,
            severity=candidate.severity,
            reason_code=candidate.reason_code,
            evidence_refs=candidate.evidence_refs,
            downstream_policy=candidate.downstream_policy,
        )

    @classmethod
    def _conflict(
        cls,
        candidate: CandidateConflict,
        requirement_id_by_candidate: Mapping[str, str],
        resolutions: Mapping[str, ResolutionDecision],
    ) -> Conflict:
        dispute_id = cls.dispute_id(candidate)
        decision = resolutions.get(dispute_id)
        resolved = decision is not None and decision.outcome == "resolved"
        selected_requirement_ids = (
            sorted(requirement_id_by_candidate[item] for item in decision.selected_candidate_ids)
            if decision is not None and resolved
            else []
        )
        return Conflict(
            id=cls._stable_id("conf", dispute_id),
            topic=candidate.topic,
            severity=candidate.severity,
            items=[requirement_id_by_candidate[item] for item in candidate.candidate_ids],
            reason_code=candidate.reason_code,
            resolution=(
                f"selected:{','.join(selected_requirement_ids)}" if resolved else None
            ),
            downstream_policy=(
                decision.downstream_policy
                if decision is not None
                else (
                    DownstreamPolicy.BLOCK
                    if candidate.severity == Severity.BLOCKER
                    else DownstreamPolicy.DO_NOT_ASSUME
                )
            ),
        )

    @classmethod
    def _audit_gaps(
        cls,
        coverage: CoverageLedger,
        segmentation: ClauseSegmentation,
        output: ExtractorOutput,
    ) -> list[UnresolvedItem]:
        clause_by_id = {item.clause_id: item for item in segmentation.clauses}
        expected: dict[CoverageClassification, set[str]] = {
            CoverageClassification.FACT: {
                ref for item in output.facts for ref in item.evidence_refs
            },
            CoverageClassification.OBJECTIVE: {
                ref for item in output.objectives for ref in item.evidence_refs
            },
            CoverageClassification.REQUIREMENT: {
                ref for item in output.requirements for ref in item.evidence_refs
            },
            CoverageClassification.REFERENCE: {
                ref for item in output.references for ref in item.evidence_refs
            },
        }
        unresolved_refs = {
            ref for item in output.unresolved_items for ref in item.evidence_refs
        }
        result: list[UnresolvedItem] = []
        for entry in coverage.entries:
            refs = expected.get(entry.classification)
            if refs is None or set(entry.evidence_refs) & (refs | unresolved_refs):
                continue
            clause = clause_by_id[entry.clause_id]
            is_requirement = entry.classification == CoverageClassification.REQUIREMENT
            payload = {
                "clause_id": entry.clause_id,
                "classification": entry.classification.value,
            }
            result.append(
                UnresolvedItem(
                    id=cls._stable_id("unresolved", payload),
                    topic=f"coverage_gap.{entry.classification.value}",
                    description=(
                        "Coverage Auditor 已识别实质内容，但 Extractor 未生成对应 Candidate。"
                    ),
                    severity=Severity.BLOCKER if is_requirement else Severity.WARNING,
                    reason_code="auditor_candidate_gap",
                    evidence_refs=[clause.evidence_id],
                    downstream_policy="block" if is_requirement else "do_not_assume",
                )
            )
        return result

    @classmethod
    def _duration_gaps(
        cls,
        coverage: CoverageLedger,
        segmentation: ClauseSegmentation,
        analyses: Sequence[DeterministicClauseAnalysis],
        output: ExtractorOutput,
    ) -> list[UnresolvedItem]:
        clause_by_id = {item.clause_id: item for item in segmentation.clauses}
        classification_by_clause = {
            item.clause_id: item.classification for item in coverage.entries
        }
        result: list[UnresolvedItem] = []
        for analysis in analyses:
            if classification_by_clause.get(analysis.clause_id) not in {
                CoverageClassification.OBJECTIVE,
                CoverageClassification.REQUIREMENT,
            }:
                continue
            evidence_id = clause_by_id[analysis.clause_id].evidence_id
            for mention in analysis.numeric_mentions:
                if mention.unit not in {"second", "minute", "hour"}:
                    continue
                covered = any(
                    evidence_id in candidate.evidence_refs
                    and cls._numeric_matches(candidate, mention)
                    for candidate in output.requirements
                    if candidate.value.amount is not None
                )
                if covered:
                    continue
                result.append(
                    UnresolvedItem(
                        id=cls._stable_id(
                            "unresolved",
                            {
                                "clause_id": analysis.clause_id,
                                "mention_id": mention.mention_id,
                                "reason": "duration_requirement_gap",
                            },
                        ),
                        topic="duration",
                        description="文本含可量化时长，但未形成可验证的时长要求。",
                        severity=Severity.WARNING,
                        reason_code="duration_requirement_gap",
                        evidence_refs=[evidence_id],
                        downstream_policy="do_not_assume",
                    )
                )
        return result

    @classmethod
    def _unclassified(
        cls,
        coverage: CoverageLedger,
        segmentation: ClauseSegmentation,
    ) -> list[UnclassifiedContent]:
        clause_by_id = {item.clause_id: item for item in segmentation.clauses}
        return [
            UnclassifiedContent(
                id=cls._stable_id("unclassified", entry.clause_id),
                description=f"未分类内容: {clause_by_id[entry.clause_id].normalized_text}",
                evidence_refs=entry.evidence_refs,
                reason_code=(entry.reason_codes[0] if entry.reason_codes else "not_classified"),
            )
            for entry in coverage.entries
            if entry.classification == CoverageClassification.UNCLASSIFIED
        ]

    @staticmethod
    def _analysis_by_evidence(
        segmentation: ClauseSegmentation,
        analyses: Sequence[DeterministicClauseAnalysis],
    ) -> dict[str, DeterministicClauseAnalysis]:
        analysis_by_clause = {item.clause_id: item for item in analyses}
        return {
            clause.evidence_id: analysis_by_clause[clause.clause_id]
            for clause in segmentation.clauses
        }

    @staticmethod
    def _stable_id(prefix: str, value: object) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"{prefix}_{sha256(encoded).hexdigest()[:24]}"
