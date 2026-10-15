"""Prompt-isolated Extractor, Coverage Auditor, and Conditional Resolver stages."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel
from brief_parser.academic_source_policy import scope_match

from brief_parser.domain.candidates import (
    AuditorOutput,
    ExtractorOutput,
    ResolverCase,
    ResolverOutput,
)
from brief_parser.domain.enums import ModelRole
from brief_parser.domain.foundation import (
    Clause,
    ClauseChunk,
    DeterministicClauseAnalysis,
    EvidenceIndex,
)
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.model_provider import (
    ModelProvider,
    ModelRequestContext,
    ProviderMessage,
    StructuredModelResult,
)
from brief_parser.ports.prompt_repository import PromptRepository


class RequirementExtractor:
    def __init__(
        self,
        provider: ModelProvider,
        prompts: PromptRepository,
        *,
        prompt_version: str = "extractor/v2",
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._prompt_version = prompt_version

    async def extract(
        self,
        *,
        chunk: ClauseChunk,
        clauses: Sequence[Clause],
        analyses: Sequence[DeterministicClauseAnalysis],
        evidence_index: EvidenceIndex,
        request_context: ModelRequestContext,
        domain_category_ids: Sequence[str] = (),
        academic_format_only: bool = False,
    ) -> StructuredModelResult[ExtractorOutput]:
        clause_by_id = {clause.clause_id: clause for clause in clauses}
        if set(clause_by_id) != set(chunk.clause_ids):
            raise ValueError("extractor clauses must exactly match the primary chunk")
        analysis_by_clause = {analysis.clause_id: analysis for analysis in analyses}
        if not set(analysis_by_clause) <= set(clause_by_id):
            raise ValueError("extractor analysis references a clause outside the chunk")
        allowed_evidence = {clause.evidence_id for clause in clauses}
        if not allowed_evidence <= set(evidence_index):
            raise ValueError("extractor chunk is missing evidence")

        payload = {
            "envelope_version": "model-input/1.0",
            "untrusted_document": True,
            "chunk_id": chunk.chunk_id,
            "clauses": [self._clause_payload(clause, academic_format_only=academic_format_only) for clause in clauses],
            "deterministic_analysis": [
                analysis.model_dump(mode="json") for analysis in analyses
            ],
            "allowed_evidence_ids": sorted(allowed_evidence),
        }
        result = await self._provider.structured_generate(
            role=ModelRole.EXTRACTOR,
            messages=self._messages(
                ModelRole.EXTRACTOR,
                payload,
                domain_category_ids=domain_category_ids,
                academic_format_only=academic_format_only,
            ),
            output_schema=ExtractorOutput,
            request_context=request_context,
        )
        if result.output is not None:
            try:
                self._validate_extractor_evidence(result.output, allowed_evidence)
            except BriefParserError:
                return _unverifiable_result(result, reason="invalid_evidence")
        return result

    def _messages(
        self,
        role: ModelRole,
        payload: Mapping[str, Any],
        *,
        domain_category_ids: Sequence[str],
        academic_format_only: bool = False,
    ) -> list[ProviderMessage]:
        template = self._prompts.get(role=role, version=self._prompt_version)
        system_content = template.content
        if academic_format_only:
            from brief_parser.compilers.academic_candidates import REGISTERED_PROPERTIES
            from brief_parser.validators.academic_decisions import ROLES
            system_content += (
                "\n\nTrusted AutoFormat scope: extract only document formatting requirements. "
                "Do not extract word counts, text/page length limits, keyword/reference counts, "
                "research or semantic content requirements, signatures or submission deadlines. "
                "Do not create questions or unresolved items for those excluded requirements. "
                "Examples and observed template styles are not explicit requirements."
                " Emit one atomic Requirement per formatting property. Use a registered "
                "property ID as value.type and a registered semantic role as subject. "
                "Do not invent a missing size, font, unit, target or condition. "
                "Preserve chapter, character and submission restrictions in the evidence. "
                "CandidateValue uses text, amount, range_end and items, not arbitrary JSON. "
                "For formatting values prefer text containing the exact literal value and "
                "unit, with amount=null and range_end=null: font size text='12pt', bold "
                "text='加粗', line spacing text='固定值20pt' or '1.5倍', size interval "
                "text='12-14pt'. Do not add a unit absent from the source. Unsupported "
                "formats remain unresolved."
                "\nTrusted formatting property IDs: " + json.dumps(sorted(REGISTERED_PROPERTIES))
                + "\nTrusted semantic roles: " + json.dumps(sorted(ROLES))
            )
        if domain_category_ids:
            system_content += (
                "\n\nTrusted Domain Pack category IDs: "
                + json.dumps(sorted(set(domain_category_ids)), ensure_ascii=False)
            )
        return [
            ProviderMessage(role="system", content=system_content),
            ProviderMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        ]

    @staticmethod
    def _clause_payload(clause: Clause, *, academic_format_only: bool = False) -> dict[str, Any]:
        return {
            "clause_id": clause.clause_id,
            "evidence_id": clause.evidence_id,
            "text": clause.normalized_text,
            "block_kind": clause.block_kind.value,
            "section_path": [part for part in clause.locator.section_path
                             if not academic_format_only or not scope_match(part)],
        }

    @staticmethod
    def _validate_extractor_evidence(
        output: ExtractorOutput,
        allowed: set[str],
    ) -> None:
        references: list[tuple[str, Sequence[str]]] = []
        for group in (output.facts, output.objectives, output.references):
            references.extend((item.candidate_id, item.evidence_refs) for item in group)
        for requirement in output.requirements:
            references.append((requirement.candidate_id, requirement.evidence_refs))
            references.append(
                (requirement.candidate_id, requirement.condition_evidence_refs)
            )
        references.extend(
            (conflict.topic, conflict.evidence_refs)
            for conflict in output.candidate_conflicts
        )
        references.extend(
            (item.topic, item.evidence_refs) for item in output.unresolved_items
        )
        _ensure_allowed_evidence(references, allowed)


class CoverageAuditor:
    def __init__(
        self,
        provider: ModelProvider,
        prompts: PromptRepository,
        *,
        prompt_version: str = "auditor/v1",
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._prompt_version = prompt_version

    async def audit(
        self,
        *,
        chunk: ClauseChunk,
        clauses: Sequence[Clause],
        extractor_output: ExtractorOutput,
        request_context: ModelRequestContext,
        academic_format_only: bool = False,
    ) -> StructuredModelResult[AuditorOutput]:
        expected = {clause.clause_id for clause in clauses}
        if expected != set(chunk.clause_ids):
            raise ValueError("auditor clauses must exactly match the primary chunk")
        evidence_by_clause = {
            clause.clause_id: clause.evidence_id for clause in clauses
        }
        payload = {
            "envelope_version": "model-input/1.0",
            "untrusted_document": True,
            "chunk_id": chunk.chunk_id,
            "clauses": [RequirementExtractor._clause_payload(item, academic_format_only=academic_format_only) for item in clauses],
            "extractor_candidate_summary": extractor_output.model_dump(mode="json"),
            "allowed_evidence_ids": sorted(evidence_by_clause.values()),
        }
        template = self._prompts.get(
            role=ModelRole.AUDITOR,
            version=self._prompt_version,
        )
        result = await self._provider.structured_generate(
            role=ModelRole.AUDITOR,
            messages=[
                ProviderMessage(role="system", content=template.content),
                ProviderMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            ],
            output_schema=AuditorOutput,
            request_context=request_context,
        )
        if result.output is not None:
            actual = {item.clause_id for item in result.output.clauses}
            if actual != expected:
                return _unverifiable_result(result, reason="invalid_clause_coverage")
            canonical_output = AuditorOutput(
                clauses=[
                    item.model_copy(
                        update={"evidence_refs": [evidence_by_clause[item.clause_id]]}
                    )
                    for item in result.output.clauses
                ]
            )
            return result.model_copy(update={"output": canonical_output})
        return result


class ConditionalResolver:
    def __init__(
        self,
        provider: ModelProvider,
        prompts: PromptRepository,
        *,
        prompt_version: str = "resolver/v1",
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._prompt_version = prompt_version

    async def resolve(
        self,
        *,
        cases: Sequence[ResolverCase],
        extractor_output: ExtractorOutput,
        evidence_index: EvidenceIndex,
        request_context: ModelRequestContext,
    ) -> StructuredModelResult[ResolverOutput]:
        if not cases:
            raise ValueError("resolver requires at least one disputed case")
        case_by_id = {case.dispute_id: case for case in cases}
        if len(case_by_id) != len(cases):
            raise ValueError("resolver dispute ids must be unique")
        candidates = {
            item.candidate_id: item
            for group in (
                extractor_output.facts,
                extractor_output.objectives,
                extractor_output.requirements,
                extractor_output.references,
            )
            for item in group
        }
        allowed_evidence: set[str] = set()
        for case in cases:
            if not set(case.candidate_ids) <= set(candidates):
                raise ValueError("resolver case references an unknown candidate")
            if not set(case.evidence_refs) <= set(evidence_index):
                raise ValueError("resolver case references unknown evidence")
            allowed_evidence.update(case.evidence_refs)

        payload = {
            "envelope_version": "model-input/1.0",
            "untrusted_document": True,
            "cases": [case.model_dump(mode="json") for case in cases],
            "candidates": {
                candidate_id: candidate.model_dump(mode="json")
                for candidate_id, candidate in candidates.items()
                if any(candidate_id in case.candidate_ids for case in cases)
            },
            "evidence": {
                evidence_id: evidence_index[evidence_id].model_dump(mode="json")
                for evidence_id in sorted(allowed_evidence)
            },
            "allowed_evidence_ids": sorted(allowed_evidence),
        }
        template = self._prompts.get(
            role=ModelRole.RESOLVER,
            version=self._prompt_version,
        )
        result = await self._provider.structured_generate(
            role=ModelRole.RESOLVER,
            messages=[
                ProviderMessage(role="system", content=template.content),
                ProviderMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            ],
            output_schema=ResolverOutput,
            request_context=request_context,
        )
        if result.output is not None:
            actual = {decision.dispute_id for decision in result.output.decisions}
            if actual != set(case_by_id):
                return _unverifiable_result(result, reason="invalid_dispute_coverage")
            for decision in result.output.decisions:
                case = case_by_id[decision.dispute_id]
                if not set(decision.selected_candidate_ids) <= set(case.candidate_ids):
                    return _unverifiable_result(result, reason="invalid_candidate_selection")
                if not set(decision.evidence_refs) <= set(case.evidence_refs):
                    return _unverifiable_result(result, reason="invalid_evidence")
        return result


def _unverifiable_result[OutputT: BaseModel](
    result: StructuredModelResult[OutputT],
    *,
    reason: str,
) -> StructuredModelResult[OutputT]:
    """Reject unsafe candidates while preserving billable call metadata."""
    return StructuredModelResult[OutputT](
        output=None,
        provider_alias=result.provider_alias,
        model_id=result.model_id,
        provider_request_id=result.provider_request_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
        completion_status="incomplete",
        incomplete_reason=reason,
        retry_count=result.retry_count,
    )


def _ensure_allowed_evidence(
    references: Sequence[tuple[str, Sequence[str]]],
    allowed: set[str],
) -> None:
    for item_id, evidence_refs in references:
        missing = set(evidence_refs) - allowed
        if missing:
            raise BriefParserError(
                ErrorCode.EVIDENCE_INVALID,
                "模型 Candidate 引用了当前 Chunk 之外的 Evidence。",
                details={"item_id": item_id, "invalid_count": len(missing)},
            )
