"""Host-neutral application service for complete input-to-Parse-Bundle execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from brief_parser.adapters.input_security import FileSecurityValidator
from brief_parser.adapters.template_layout import DocxTemplateLayoutReader
from brief_parser.application.bundle import build_academic_parse_bundle, build_parse_bundle
from brief_parser.application.output_compilation import OutputCompiler
from brief_parser.application.pipeline import BriefParsingPipeline, ParsePipelineRequest
from brief_parser.application.resource_limits import ParseResourceLimits
from brief_parser.compilers.academic_common import AcademicCommonFormatExtractor
from brief_parser.compilers.template_layout import build_template_report
from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.bundle import ParseBundle
from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.pipeline import PipelineResult
from brief_parser.domain.requirement_ir import DomainPackRef
from brief_parser.errors import BriefParserError, ErrorCode
from brief_parser.ports.document_ingestion import SecuredSource


@dataclass(frozen=True, slots=True)
class TextSourceInput:
    text: str
    client_source_id: str = "stdin"


@dataclass(frozen=True, slots=True)
class ParseServiceRequest:
    request_id: str
    domain_pack_id: str
    requested_task_types: tuple[str, ...]
    source_paths: tuple[Path, ...] = ()
    text_sources: tuple[TextSourceInput, ...] = ()
    domain_pack_version: str | None = None
    locale: str = "zh-CN"
    artifact_version: int = 1


class DomainPackCatalog:
    def __init__(self, packs: dict[tuple[str, str], DomainPack]) -> None:
        if not packs:
            raise ValueError("domain pack catalog cannot be empty")
        self._packs = dict(packs)

    def resolve(self, pack_id: str, version: str | None = None) -> DomainPack:
        if version is not None:
            pack = self._packs.get((pack_id, version))
            if pack is None:
                raise BriefParserError(
                    ErrorCode.DOMAIN_PACK_INVALID,
                    "请求的 Domain Pack 版本不存在。",
                    details={"domain": pack_id, "version": version},
                )
            return pack
        candidates = [
            pack for (candidate_id, _), pack in self._packs.items() if candidate_id == pack_id
        ]
        if not candidates:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "请求的 Domain Pack 不存在。",
                details={"domain": pack_id},
            )
        return max(candidates, key=lambda item: _semantic_version_key(item.version))


class BriefParserService:
    """Application boundary shared by CLI, standalone API, and future hosts."""

    def __init__(
        self,
        pipeline: BriefParsingPipeline,
        catalog: DomainPackCatalog,
        *,
        security: FileSecurityValidator | None = None,
        compiler: OutputCompiler | None = None,
        resource_limits: ParseResourceLimits | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._catalog = catalog
        self._security = security or FileSecurityValidator()
        self._compiler = compiler or OutputCompiler()
        self._resource_limits = resource_limits or ParseResourceLimits()

    async def parse_with_timeout(
        self,
        request: ParseServiceRequest,
        *,
        timeout_seconds: float,
    ) -> ParseBundle:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        try:
            return await asyncio.wait_for(
                self.parse(request),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise BriefParserError(
                ErrorCode.PROVIDER_TRANSIENT,
                "Parse Job 超过允许执行时间。",
                retryable=True,
                details={"timeout_seconds": timeout_seconds},
            ) from exc

    async def parse(self, request: ParseServiceRequest) -> ParseBundle:
        pipeline_result, pack, _ = await self._run_pipeline(request)
        outputs = self._compiler.compile(
            pipeline_result.requirement_ir,
            pack,
            task_types=request.requested_task_types,
        )
        return build_parse_bundle(pipeline_result, outputs)

    async def parse_academic(self, request: ParseServiceRequest) -> AcademicParseBundle:
        """Parse academic Brief facts without producing a generic ExecutionBrief."""
        if (request.domain_pack_id != "academic_paper"
                or request.requested_task_types != ("format_academic_paper",)):
            raise BriefParserError(
                ErrorCode.INVALID_REQUEST,
                "论文 parse-only 仅接受 format_academic_paper 任务标识。",
            )
        pipeline_result, pack, sources = await self._run_pipeline(request)
        outputs = self._compiler.compile_parse_only(pipeline_result.requirement_ir, pack)
        format_ruleset = AcademicCommonFormatExtractor().extract(
            outputs.requirement_ir,
        )
        return build_academic_parse_bundle(
            pipeline_result, outputs, format_ruleset=format_ruleset,
            template_layout=build_template_report(
                DocxTemplateLayoutReader().read(sources), outputs.requirement_ir, format_ruleset,
            ),
        )

    async def parse_academic_with_timeout(
        self,
        request: ParseServiceRequest,
        *,
        timeout_seconds: float,
    ) -> AcademicParseBundle:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        try:
            return await asyncio.wait_for(
                self.parse_academic(request), timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise BriefParserError(
                ErrorCode.PROVIDER_TRANSIENT,
                "论文 Parse Job 超过允许执行时间。",
                retryable=True,
                details={"timeout_seconds": timeout_seconds},
            ) from exc

    async def _run_pipeline(
        self, request: ParseServiceRequest,
    ) -> tuple[PipelineResult, DomainPack, tuple[SecuredSource, ...]]:
        if not request.source_paths and not request.text_sources:
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "至少需要一个输入 Source。")
        self._resource_limits.validate_source_count(
            len(request.source_paths) + len(request.text_sources)
        )
        if not request.requested_task_types:
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "至少需要一个下游任务类型。")
        if len(request.requested_task_types) != len(set(request.requested_task_types)):
            raise BriefParserError(ErrorCode.INVALID_REQUEST, "下游任务类型不能重复。")

        pack = self._catalog.resolve(
            request.domain_pack_id,
            request.domain_pack_version,
        )
        if request.locale not in pack.locales:
            raise BriefParserError(
                ErrorCode.DOMAIN_PACK_INVALID,
                "Domain Pack 不支持请求的 locale。",
                details={"domain": pack.id, "locale": request.locale},
            )

        sources = []
        ordinal = 0
        for path in request.source_paths:
            ordinal += 1
            sources.append(
                self._security.secure_file(
                    path,
                    source_id=f"src_{ordinal:03d}",
                    client_source_id=f"file_{ordinal:03d}",
                    language_hints=(request.locale,),
                )
            )
        for text_source in request.text_sources:
            ordinal += 1
            sources.append(
                self._security.secure_text(
                    text_source.text,
                    source_id=f"src_{ordinal:03d}",
                    client_source_id=text_source.client_source_id,
                    language_hints=(request.locale,),
                )
            )
        self._resource_limits.validate_secured_sources(sources)

        pipeline_result = await self._pipeline.run(
            ParsePipelineRequest(
                request_id=request.request_id,
                sources=tuple(sources),
                domain_pack=DomainPackRef(id=pack.id, version=pack.version),
                requested_task_types=request.requested_task_types,
                domain_category_ids=tuple(category.id for category in pack.categories),
                domain_category_risks=tuple(
                    (category.id, category.risk) for category in pack.categories
                ),
                artifact_version=request.artifact_version,
                locale=request.locale,
            )
        )
        return pipeline_result, pack, tuple(sources)


def _semantic_version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)
