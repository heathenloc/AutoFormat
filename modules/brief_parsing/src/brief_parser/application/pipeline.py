"""Phase 4 end-to-end parsing orchestration."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from pydantic import BaseModel

from brief_parser.adapters.bounded_provider import BoundedModelProvider
from brief_parser.adapters.clause_segmenter import ClauseSegmenter
from brief_parser.adapters.academic_clause_segmenter import AcademicClauseSegmenter
from brief_parser.academic_source_policy import classify_evidence, is_excluded_candidate, scope_match
from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.evidence_index import EvidenceIndexBuilder
from brief_parser.adapters.observability import NullObservationSink
from brief_parser.application.ir_assembler import RequirementIRAssembler, SourceQuality
from brief_parser.application.model_stages import (
    ConditionalResolver,
    CoverageAuditor,
    RequirementExtractor,
)
from brief_parser.application.resource_limits import ParseResourceLimits
from brief_parser.domain.candidates import (
    CandidateConflict,
    CandidateItem,
    CandidateReference,
    CandidateRequirement,
    CandidateUnresolved,
    ExtractorOutput,
    ResolutionDecision,
    ResolverCase,
)
from brief_parser.domain.document import ExtractedDocument, ExtractionQualityStatus
from brief_parser.domain.enums import ModelRole, Priority
from brief_parser.domain.foundation import (
    Clause,
    ClauseChunk,
    ClauseSegmentation,
    CoverageClassification,
    DeterministicClauseAnalysis,
    EvidenceIndex,
)
from brief_parser.domain.pipeline import (
    ParseManifest,
    PipelineResult,
    PipelineSourceRecord,
    ProviderCallRecord,
    StageRecord,
)
from brief_parser.domain.requirement_ir import DomainPackRef, PipelineInfo
from brief_parser.ports.document_ingestion import DocumentIngestionPort, SecuredSource
from brief_parser.ports.model_provider import (
    ModelProvider,
    ModelRequestContext,
    StructuredModelResult,
)
from brief_parser.ports.observability import ObservationSink, PipelineObservation
from brief_parser.ports.prompt_repository import PromptRepository
from brief_parser.validators.conflict import ConflictDetector, ResolutionEvidencePolicy
from brief_parser.validators.coverage import CoverageLedgerBuilder
from brief_parser.validators.deterministic_rules import DeterministicRuleAnalyzer
from brief_parser.version import PIPELINE_VERSION

_SAFE_MODEL_FAILURE_REASONS = frozenset(
    {
        "invalid_evidence",
        "invalid_clause_coverage",
        "invalid_dispute_coverage",
        "invalid_candidate_selection",
        "schema_invalid",
        "max_completion_tokens",
    }
)
_PRIORITY_RANK = {
    Priority.LOW: 0,
    Priority.NORMAL: 1,
    Priority.HIGH: 2,
    Priority.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class ParsePipelineRequest:
    request_id: str
    sources: tuple[SecuredSource, ...]
    domain_pack: DomainPackRef
    requested_task_types: tuple[str, ...]
    domain_category_ids: tuple[str, ...] = ()
    domain_category_risks: tuple[tuple[str, Priority], ...] = ()
    artifact_version: int = 1
    locale: str = "zh-CN"


@dataclass(slots=True)
class _JobTokenBudget:
    limit: int
    used: int = 0
    exceeded: bool = False

    def record(self, *, input_tokens: int, output_tokens: int) -> None:
        self.used += input_tokens + output_tokens
        self.exceeded = self.used > self.limit


class BriefParsingPipeline:
    """Run secured sources through evidence-first extraction into a verifiable IR."""

    def __init__(
        self,
        provider: ModelProvider,
        prompts: PromptRepository,
        *,
        model_routes: Mapping[ModelRole, str],
        prompt_versions: Mapping[ModelRole, str] | None = None,
        ingestor: DocumentIngestionPort | None = None,
        segmenter: ClauseSegmenter | None = None,
        evidence_builder: EvidenceIndexBuilder | None = None,
        rule_analyzer: DeterministicRuleAnalyzer | None = None,
        coverage_builder: CoverageLedgerBuilder | None = None,
        conflict_detector: ConflictDetector | None = None,
        resolution_policy: ResolutionEvidencePolicy | None = None,
        assembler: RequirementIRAssembler | None = None,
        clock: Callable[[], datetime] | None = None,
        provider_max_concurrency: int = 4,
        job_token_budget: int = 100_000,
        observer: ObservationSink | None = None,
        resource_limits: ParseResourceLimits | None = None,
    ) -> None:
        if provider_max_concurrency <= 0:
            raise ValueError("provider_max_concurrency must be positive")
        if job_token_budget <= 0:
            raise ValueError("job_token_budget must be positive")
        bounded_provider = BoundedModelProvider(
            provider,
            max_concurrency=provider_max_concurrency,
        )
        self._provider = bounded_provider
        self._job_token_budget = job_token_budget
        self._observer = observer or NullObservationSink()
        self._resource_limits = resource_limits or ParseResourceLimits()
        self._prompts = prompts
        self._model_routes = dict(model_routes)
        self._prompt_versions = {
            ModelRole.EXTRACTOR: "extractor/v2",
            ModelRole.AUDITOR: "auditor/v1",
            ModelRole.RESOLVER: "resolver/v1",
        }
        if prompt_versions is not None:
            self._prompt_versions.update(prompt_versions)
        self._ingestor = ingestor or DocumentIngestor()
        self._segmenter = segmenter or ClauseSegmenter()
        self._evidence_builder = evidence_builder or EvidenceIndexBuilder()
        self._rule_analyzer = rule_analyzer or DeterministicRuleAnalyzer()
        self._coverage_builder = coverage_builder or CoverageLedgerBuilder()
        self._conflict_detector = conflict_detector or ConflictDetector()
        self._resolution_policy = resolution_policy or ResolutionEvidencePolicy()
        self._assembler = assembler or RequirementIRAssembler()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._extractor = RequirementExtractor(
            bounded_provider,
            prompts,
            prompt_version=self._prompt_versions[ModelRole.EXTRACTOR],
        )
        self._auditor = CoverageAuditor(
            bounded_provider,
            prompts,
            prompt_version=self._prompt_versions[ModelRole.AUDITOR],
        )
        self._resolver = ConditionalResolver(
            bounded_provider,
            prompts,
            prompt_version=self._prompt_versions[ModelRole.RESOLVER],
        )

    async def run(self, request: ParsePipelineRequest) -> PipelineResult:
        self._validate_request(request)
        pipeline_started = perf_counter()
        stages: list[StageRecord] = []
        provider_calls: list[ProviderCallRecord] = []
        token_budget = _JobTokenBudget(self._job_token_budget)

        started = perf_counter()
        documents = [self._ingestor.ingest(source) for source in request.sources]
        self._resource_limits.validate_documents(documents)
        stages.append(self._stage("ingestion", started, len(documents)))

        started = perf_counter()
        academic = request.domain_pack.id == "academic_paper"
        segmenter = self._segmenter
        if academic and type(segmenter) is ClauseSegmenter:
            segmenter = AcademicClauseSegmenter(
                long_block_chars=segmenter._long_block_chars,
                target_chunk_tokens=segmenter._target_chunk_tokens,
                hard_chunk_tokens=segmenter._hard_chunk_tokens,
            )
        segmentations = [segmenter.segment(document) for document in documents]
        segmentation = self._merge_segmentations(segmentations)
        stages.append(self._stage("clause_segmentation", started, len(segmentation.clauses)))

        started = perf_counter()
        evidence_index: EvidenceIndex = {}
        analyses: list[DeterministicClauseAnalysis] = []
        for document, local_segmentation in zip(documents, segmentations, strict=True):
            local_evidence = self._evidence_builder.build(document, local_segmentation)
            duplicates = set(evidence_index) & set(local_evidence)
            if duplicates:
                raise ValueError(f"duplicate evidence ids: {sorted(duplicates)}")
            evidence_index.update(local_evidence)
            analyses.extend(self._rule_analyzer.analyze(document, local_segmentation))
        stages.append(self._stage("deterministic_rules", started, len(analyses)))

        parser_versions = self._parser_versions(documents)
        fingerprint = self._fingerprint(request, parser_versions)
        artifact_id = f"art_{sha256(fingerprint.encode('ascii')).hexdigest()[:24]}"
        context = ModelRequestContext(
            request_id=request.request_id,
            trace_id=f"trace_{fingerprint[:24]}",
            source_ids=[item.source_id for item in request.sources],
        )
        clause_by_id = {item.clause_id: item for item in segmentation.clauses}
        analysis_by_clause = {item.clause_id: item for item in analyses}
        category_risks = dict(request.domain_category_risks)

        completed_outputs: list[tuple[str, ExtractorOutput]] = []
        classifications: dict[str, CoverageClassification] = {}
        reason_codes: dict[str, list[str]] = {}
        provider_unverifiable = False
        model_chunks = segmentation.chunks
        if academic:
            decisions = {item.evidence_id: item for item in classify_evidence(evidence_index.values())}
            allowed = set()
            for clause in segmentation.clauses:
                decision = decisions[clause.evidence_id]
                if decision.source_class in {"explicit_requirement", "uncertain"} and not scope_match(clause.raw_text):
                    allowed.add(clause.clause_id)
                else:
                    classifications[clause.clause_id] = CoverageClassification.CONTEXT
                    reason_codes[clause.clause_id] = [decision.reason_code]
            model_chunks = [chunk.model_copy(update={
                "clause_ids": [identifier for identifier in chunk.clause_ids if identifier in allowed],
            }) for chunk in segmentation.chunks if any(identifier in allowed for identifier in chunk.clause_ids)]

        started = perf_counter()
        completed_extractors = 0
        extractor_failure_reason: str | None = None
        for chunk in model_chunks:
            clauses = [clause_by_id[item] for item in chunk.clause_ids]
            chunk_analyses = [analysis_by_clause[item] for item in chunk.clause_ids]
            extractor_result = await self._extractor.extract(
                chunk=chunk,
                clauses=clauses,
                analyses=chunk_analyses,
                evidence_index=evidence_index,
                request_context=context,
                domain_category_ids=request.domain_category_ids,
                academic_format_only=academic,
            )
            provider_calls.append(
                self._provider_record(ModelRole.EXTRACTOR, extractor_result)
            )
            token_budget.record(
                input_tokens=extractor_result.token_usage.input_tokens,
                output_tokens=extractor_result.token_usage.output_tokens,
            )
            if token_budget.exceeded:
                provider_unverifiable = True
            if extractor_result.output is None:
                provider_unverifiable = True
                failure_reason = self._model_failure_reason(
                    extractor_result.completion_status,
                    extractor_result.incomplete_reason,
                )
                extractor_failure_reason = extractor_failure_reason or failure_reason
                for clause in clauses:
                    reason_codes[clause.clause_id] = [
                        f"extractor_{failure_reason}"
                    ]
            else:
                completed_extractors += 1
                completed_outputs.append(
                    (
                        chunk.chunk_id,
                        self._apply_category_risk_floor(
                            self._filter_academic_output(extractor_result.output) if academic else extractor_result.output,
                            category_risks,
                        ),
                    )
                )
            if token_budget.exceeded:
                break
        stages.append(
            self._stage(
                "extractor",
                started,
                completed_extractors,
                reason_code=(
                    "job_token_budget_exceeded"
                    if token_budget.exceeded
                    else extractor_failure_reason
                ),
            )
        )

        started = perf_counter()
        completed_audits = 0
        auditor_failure_reason: str | None = None
        output_by_chunk = dict(completed_outputs)
        if token_budget.exceeded:
            stages.append(
                StageRecord(
                    stage="coverage_auditor",
                    status="skipped",
                    duration_ms=0,
                    item_count=0,
                    reason_code="job_token_budget_exceeded",
                )
            )
        else:
            for chunk in model_chunks:
                extractor_output = output_by_chunk.get(chunk.chunk_id)
                if extractor_output is None:
                    continue
                clauses = [clause_by_id[item] for item in chunk.clause_ids]
                audit_result = await self._auditor.audit(
                    chunk=chunk,
                    clauses=clauses,
                    extractor_output=extractor_output,
                    request_context=context,
                    academic_format_only=academic,
                )
                provider_calls.append(
                    self._provider_record(ModelRole.AUDITOR, audit_result)
                )
                token_budget.record(
                    input_tokens=audit_result.token_usage.input_tokens,
                    output_tokens=audit_result.token_usage.output_tokens,
                )
                if token_budget.exceeded:
                    provider_unverifiable = True
                if audit_result.output is None:
                    provider_unverifiable = True
                    failure_reason = self._model_failure_reason(
                        audit_result.completion_status,
                        audit_result.incomplete_reason,
                    )
                    auditor_failure_reason = auditor_failure_reason or failure_reason
                    for clause in clauses:
                        reason_codes[clause.clause_id] = [
                            f"auditor_{failure_reason}"
                        ]
                else:
                    completed_audits += 1
                    for audit in audit_result.output.clauses:
                        classifications[audit.clause_id] = audit.classification
                        reason_codes[audit.clause_id] = [audit.reason_code]
                if token_budget.exceeded:
                    break
            stages.append(
                self._stage(
                    "coverage_auditor",
                    started,
                    completed_audits,
                    reason_code=(
                        "job_token_budget_exceeded"
                        if token_budget.exceeded
                        else auditor_failure_reason
                    ),
                )
            )

        if token_budget.exceeded:
            for clause in segmentation.clauses:
                if clause.clause_id not in classifications:
                    reason_codes[clause.clause_id] = ["job_token_budget_exceeded"]

        merged_output = self._merge_extractor_outputs(completed_outputs)
        started = perf_counter()
        conflicts = self._conflict_detector.detect(merged_output)
        stages.append(self._stage("conflict_detection", started, len(conflicts)))

        resolutions: dict[str, ResolutionDecision] = {}
        if conflicts and not provider_unverifiable:
            started = perf_counter()
            cases = [self._resolver_case(item) for item in conflicts]
            resolver_result = await self._resolver.resolve(
                cases=cases,
                extractor_output=merged_output,
                evidence_index=evidence_index,
                request_context=context,
            )
            provider_calls.append(
                self._provider_record(ModelRole.RESOLVER, resolver_result)
            )
            token_budget.record(
                input_tokens=resolver_result.token_usage.input_tokens,
                output_tokens=resolver_result.token_usage.output_tokens,
            )
            if token_budget.exceeded:
                provider_unverifiable = True
            rejected_resolution = False
            if resolver_result.output is None:
                provider_unverifiable = True
            else:
                for decision in resolver_result.output.decisions:
                    if self._resolution_policy.is_supported(decision, evidence_index):
                        resolutions[decision.dispute_id] = decision
                    else:
                        rejected_resolution = True
            stages.append(
                self._stage(
                    "conditional_resolver",
                    started,
                    len(resolutions),
                    reason_code=(
                        "job_token_budget_exceeded"
                        if token_budget.exceeded
                        else (
                            (
                                "unsupported_resolution_preserved"
                                if rejected_resolution
                                else None
                            )
                            if resolver_result.output is not None
                            else self._model_failure_reason(
                                resolver_result.completion_status,
                                resolver_result.incomplete_reason,
                            )
                        )
                    ),
                )
            )
        else:
            stages.append(
                StageRecord(
                    stage="conditional_resolver",
                    status="skipped",
                    duration_ms=0,
                    item_count=0,
                    reason_code=(
                        "job_token_budget_exceeded"
                        if token_budget.exceeded
                        else (
                            "upstream_provider_unverifiable"
                            if provider_unverifiable
                            else "no_disputes"
                        )
                    ),
                )
            )

        coverage = self._coverage_builder.build(
            segmentation,
            evidence_index,
            classifications=classifications,
            reason_codes=reason_codes,
        )
        created_at = self._clock()
        if created_at.utcoffset() is None:
            raise ValueError("pipeline clock must return a timezone-aware datetime")
        pipeline_info = PipelineInfo(
            version=PIPELINE_VERSION,
            parser_versions=parser_versions,
            prompt_versions={
                role.value: version for role, version in self._prompt_versions.items()
            },
            model_configs={role.value: route for role, route in self._model_routes.items()},
        )
        source_quality = {
            document.source_manifest.source_id: self._source_quality(document.quality.status)
            for document in documents
        }
        started = perf_counter()
        requirement_ir = self._assembler.assemble(
            request_id=request.request_id,
            artifact_id=artifact_id,
            artifact_version=request.artifact_version,
            created_at=created_at,
            locale=request.locale,
            domain_pack=request.domain_pack,
            pipeline_info=pipeline_info,
            source_manifests=[item.source_manifest for item in documents],
            source_quality=source_quality,
            segmentation=segmentation,
            evidence_index=evidence_index,
            analyses=analyses,
            extractor_output=merged_output,
            conflicts=conflicts,
            resolutions=resolutions,
            coverage=coverage,
            provider_calls=provider_calls,
            provider_unverifiable=provider_unverifiable,
            job_token_budget_exceeded=token_budget.exceeded,
        )
        stages.append(self._stage("ir_assembly", started, len(requirement_ir.requirements)))

        manifest = ParseManifest(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            artifact_id=artifact_id,
            artifact_version=request.artifact_version,
            created_at=created_at,
            locale=request.locale,
            pipeline_version=PIPELINE_VERSION,
            domain_pack=request.domain_pack,
            requested_task_types=sorted(set(request.requested_task_types)),
            prompt_versions=pipeline_info.prompt_versions,
            model_routes={role.value: route for role, route in self._model_routes.items()},
            sources=[
                PipelineSourceRecord(
                    source_id=item.source_manifest.source_id,
                    sha256=item.source_manifest.sha256,
                    parser_id=item.source_manifest.parser_id,
                    parser_version=item.source_manifest.parser_version,
                    extraction_status=item.source_manifest.extraction_status,
                )
                for item in documents
            ],
            stages=stages,
            provider_calls=provider_calls,
            readiness_reason_codes=requirement_ir.quality.readiness_reason_codes,
        )
        result = PipelineResult(requirement_ir=requirement_ir, manifest=manifest)
        self._observer.record_pipeline(
            PipelineObservation(
                trace_id=context.trace_id,
                request_id=request.request_id,
                duration_ms=max(0, int((perf_counter() - pipeline_started) * 1000)),
                readiness=requirement_ir.readiness,
                clause_count=requirement_ir.quality.clause_count,
                stages=stages,
                provider_calls=provider_calls,
                readiness_reason_codes=requirement_ir.quality.readiness_reason_codes,
            )
        )
        return result

    def _fingerprint(
        self,
        request: ParsePipelineRequest,
        parser_versions: Mapping[str, str],
    ) -> str:
        payload = {
            "source_sha256": [
                {"source_id": item.source_id, "sha256": item.sha256}
                for item in sorted(request.sources, key=lambda source: source.source_id)
            ],
            "domain_pack": request.domain_pack.model_dump(mode="json"),
            "domain_category_ids": sorted(set(request.domain_category_ids)),
            "domain_category_risks": {
                category_id: risk.value
                for category_id, risk in sorted(request.domain_category_risks)
            },
            "pipeline_version": PIPELINE_VERSION,
            "parser_versions": dict(sorted(parser_versions.items())),
            "prompt_versions": {
                role.value: version
                for role, version in sorted(
                    self._prompt_versions.items(), key=lambda item: item[0].value
                )
            },
            "model_routes": {
                role.value: route
                for role, route in sorted(
                    self._model_routes.items(), key=lambda item: item[0].value
                )
            },
            "requested_task_types": sorted(set(request.requested_task_types)),
        }
        if request.domain_pack.id == "academic_paper":
            payload["academic_scope_policy"] = "academic-format-scope/1.2"
            payload["academic_rule_projector"] = "1.5.0"
            payload["academic_candidate_guidance"] = "1.0"
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _validate_request(self, request: ParsePipelineRequest) -> None:
        if not request.sources:
            raise ValueError("pipeline requires at least one secured source")
        if not request.requested_task_types:
            raise ValueError("pipeline requires at least one requested task type")
        self._resource_limits.validate_secured_sources(request.sources)
        if request.artifact_version <= 0:
            raise ValueError("artifact_version must be positive")
        source_ids = [item.source_id for item in request.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("pipeline source ids must be unique")
        risk_ids = [category_id for category_id, _ in request.domain_category_risks]
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("domain category risk ids must be unique")
        if not set(risk_ids) <= set(request.domain_category_ids):
            raise ValueError("domain category risks require matching category ids")
        for source in request.sources:
            if source.byte_size != len(source.content):
                raise ValueError(f"source {source.source_id!r} byte_size does not match content")
            if sha256(source.content).hexdigest() != source.sha256:
                raise ValueError(f"source {source.source_id!r} sha256 does not match content")

    @staticmethod
    def _merge_segmentations(
        segmentations: Sequence[ClauseSegmentation],
    ) -> ClauseSegmentation:
        clauses: list[Clause] = []
        chunks: list[ClauseChunk] = []
        for segmentation in segmentations:
            for clause in segmentation.clauses:
                clauses.append(clause.model_copy(update={"ordinal": len(clauses)}))
            for chunk in segmentation.chunks:
                chunks.append(chunk.model_copy(update={"ordinal": len(chunks)}))
        return ClauseSegmentation(clauses=clauses, chunks=chunks)

    @classmethod
    def _merge_extractor_outputs(
        cls,
        outputs: Sequence[tuple[str, ExtractorOutput]],
    ) -> ExtractorOutput:
        facts: list[CandidateItem] = []
        objectives: list[CandidateItem] = []
        requirements: list[CandidateRequirement] = []
        references: list[CandidateReference] = []
        conflicts: list[CandidateConflict] = []
        unresolved: list[CandidateUnresolved] = []
        for chunk_id, output in outputs:
            id_map = {
                item.candidate_id: f"{chunk_id}.{item.candidate_id}"
                for group in (
                    output.facts,
                    output.objectives,
                    output.requirements,
                    output.references,
                )
                for item in group
            }
            facts.extend(
                item.model_copy(update={"candidate_id": id_map[item.candidate_id]})
                for item in output.facts
            )
            objectives.extend(
                item.model_copy(update={"candidate_id": id_map[item.candidate_id]})
                for item in output.objectives
            )
            requirements.extend(
                item.model_copy(update={"candidate_id": id_map[item.candidate_id]})
                for item in output.requirements
            )
            references.extend(
                item.model_copy(update={"candidate_id": id_map[item.candidate_id]})
                for item in output.references
            )
            conflicts.extend(
                item.model_copy(
                    update={
                        "candidate_ids": [id_map[candidate] for candidate in item.candidate_ids]
                    }
                )
                for item in output.candidate_conflicts
            )
            unresolved.extend(output.unresolved_items)
        return ExtractorOutput(
            facts=facts,
            objectives=objectives,
            requirements=requirements,
            references=references,
            candidate_conflicts=conflicts,
            unresolved_items=unresolved,
        )

    @staticmethod
    def _parser_versions(documents: Sequence[ExtractedDocument]) -> dict[str, str]:
        versions: dict[str, str] = {}
        for document in documents:
            manifest = document.source_manifest
            current = versions.get(manifest.parser_id)
            if current is not None and current != manifest.parser_version:
                raise ValueError("one parser id reported multiple versions")
            versions[manifest.parser_id] = manifest.parser_version
        return versions

    @staticmethod
    def _provider_record[OutputT: BaseModel](
        role: ModelRole,
        result: StructuredModelResult[OutputT],
    ) -> ProviderCallRecord:
        return ProviderCallRecord(
            role=role,
            provider_alias=result.provider_alias,
            model_id=result.model_id,
            provider_request_id=result.provider_request_id,
            completion_status=result.completion_status,
            input_tokens=result.token_usage.input_tokens,
            output_tokens=result.token_usage.output_tokens,
            latency_ms=result.latency_ms,
            retry_count=result.retry_count,
        )

    @classmethod
    def _resolver_case(cls, conflict: CandidateConflict) -> ResolverCase:
        return ResolverCase(
            dispute_id=RequirementIRAssembler.dispute_id(conflict),
            reason_code=conflict.reason_code,
            candidate_ids=conflict.candidate_ids,
            evidence_refs=conflict.evidence_refs,
            description=f"Requirement 候选在 {conflict.topic} 上存在冲突。",
        )

    @staticmethod
    def _filter_academic_output(output: ExtractorOutput) -> ExtractorOutput:
        def allowed(item: CandidateItem | CandidateRequirement) -> bool:
            labels = [item.label, item.value.text or "", *item.value.items]
            if isinstance(item, CandidateRequirement):
                labels += [item.semantic_key, item.category, item.value.type]
            # A5 + a page property in another field must not become "5 pages".
            return not any(is_excluded_candidate(label) for label in labels)

        requirements = [item for item in output.requirements if allowed(item)]
        ids = {item.candidate_id for item in requirements}
        return ExtractorOutput(
            facts=[item for item in output.facts if allowed(item)],
            objectives=[item for item in output.objectives if allowed(item)],
            requirements=requirements,
            references=[item for item in output.references if allowed(item)],
            candidate_conflicts=[item for item in output.candidate_conflicts if set(item.candidate_ids) <= ids],
            unresolved_items=[item for item in output.unresolved_items if not is_excluded_candidate(
                item.topic + " " + item.description + " " + item.reason_code
            )],
        )

    @staticmethod
    def _apply_category_risk_floor(
        output: ExtractorOutput,
        category_risks: Mapping[str, Priority],
    ) -> ExtractorOutput:
        requirements = []
        for candidate in output.requirements:
            minimum = category_risks.get(candidate.category)
            if minimum is not None and _PRIORITY_RANK[minimum] > _PRIORITY_RANK[
                candidate.priority
            ]:
                candidate = candidate.model_copy(update={"priority": minimum})
            requirements.append(candidate)
        return output.model_copy(update={"requirements": requirements})

    @staticmethod
    def _model_failure_reason(status: str, reason: str | None) -> str:
        if status == "incomplete" and reason in _SAFE_MODEL_FAILURE_REASONS:
            return reason
        return "provider_refused" if status == "refused" else "provider_incomplete"

    @staticmethod
    def _source_quality(status: ExtractionQualityStatus) -> SourceQuality:
        quality_by_status: dict[ExtractionQualityStatus, SourceQuality] = {
            ExtractionQualityStatus.PASS: "complete",
            ExtractionQualityStatus.WARNING: "degraded",
            ExtractionQualityStatus.REJECT: "failed",
        }
        return quality_by_status[status]

    @staticmethod
    def _stage(
        name: str,
        started: float,
        item_count: int,
        *,
        reason_code: str | None = None,
    ) -> StageRecord:
        return StageRecord(
            stage=name,
            status="completed",
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            item_count=item_count,
            reason_code=reason_code,
        )
