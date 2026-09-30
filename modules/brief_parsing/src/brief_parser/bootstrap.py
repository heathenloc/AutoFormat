"""Composition root for standalone execution without host-application coupling."""

from __future__ import annotations

from pathlib import Path

from brief_parser.adapters.document_ingestion import DocumentIngestor
from brief_parser.adapters.fake_provider import FakeModelProvider
from brief_parser.adapters.input_security import FileSecurityValidator, InputSecurityPolicy
from brief_parser.adapters.observability import (
    CompositeObservationSink,
    JsonLogObservationSink,
    build_otlp_http_observation_sink,
)
from brief_parser.adapters.openai_provider import (
    OpenAIModelProvider,
    OpenAIModelRoute,
    OpenAIProviderConfig,
)
from brief_parser.adapters.process_isolation import (
    ParserProcessLimits,
    ProcessIsolatedDocumentIngestor,
    hard_process_isolation_supported,
)
from brief_parser.adapters.prompt_repository import FilePromptRepository
from brief_parser.adapters.qwen_provider import (
    QwenModelProvider,
    QwenModelRoute,
    QwenProviderConfig,
)
from brief_parser.application.pipeline import BriefParsingPipeline
from brief_parser.application.resource_limits import ParseResourceLimits
from brief_parser.application.service import BriefParserService, DomainPackCatalog
from brief_parser.compilers.context import CompilerRegistry
from brief_parser.compilers.domain_validation import DomainValidatorRegistry
from brief_parser.config import Settings
from brief_parser.domain.enums import ModelRole
from brief_parser.domain_packs.loader import DomainPackLoader, DomainPackReferenceRegistry
from brief_parser.ports.model_provider import ModelProvider
from brief_parser.ports.observability import ObservationSink
from brief_parser.version import __version__


def build_domain_pack_loader() -> DomainPackLoader:
    validators = DomainValidatorRegistry.builtins()
    compilers = CompilerRegistry.builtins()
    return DomainPackLoader(
        DomainPackReferenceRegistry(
            validator_ids=validators.ids,
            compiler_ids=compilers.ids,
        )
    )


def runtime_resource_dirs() -> tuple[Path, Path]:
    project_root = Path(__file__).resolve().parents[2]
    project_prompts = project_root / "prompts"
    project_packs = project_root / "domain_packs"
    if project_prompts.is_dir() and project_packs.is_dir():
        return project_prompts, project_packs

    package_root = Path(__file__).resolve().parent
    installed_prompts = package_root / "prompts"
    installed_packs = package_root / "domain_packs_data"
    if installed_prompts.is_dir() and installed_packs.is_dir():
        return installed_prompts, installed_packs
    raise RuntimeError("packaged prompts and Domain Packs are unavailable")


def build_model_provider(settings: Settings) -> ModelProvider:
    model_ids = {
        ModelRole.EXTRACTOR: settings.extractor_model,
        ModelRole.AUDITOR: settings.auditor_model,
        ModelRole.RESOLVER: settings.resolver_model,
    }
    if settings.provider == "fake":
        return FakeModelProvider(model_ids=model_ids)
    if settings.provider == "qwen":
        if settings.qwen_api_key is None:
            raise ValueError("DASHSCOPE_API_KEY is required for the qwen provider")
        routes = {
            role: QwenModelRoute(
                model_id=model_id,
                enable_thinking=settings.qwen_enable_thinking,
            )
            for role, model_id in model_ids.items()
        }
        return QwenModelProvider(
            QwenProviderConfig(
                api_key=settings.qwen_api_key,
                base_url=settings.qwen_base_url,
                routes=routes,
                connect_timeout_seconds=settings.provider_connect_timeout_seconds,
                read_timeout_seconds=settings.provider_read_timeout_seconds,
                transient_max_retries=settings.provider_max_retries,
                incomplete_max_retries=settings.structured_output_max_retries,
            )
        )
    if settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY is required for the openai provider")
    return OpenAIModelProvider(
        OpenAIProviderConfig(
            api_key=settings.openai_api_key,
            routes={
                ModelRole.EXTRACTOR: OpenAIModelRoute(
                    model_id=settings.extractor_model,
                    reasoning_effort=settings.extractor_reasoning,
                ),
                ModelRole.AUDITOR: OpenAIModelRoute(
                    model_id=settings.auditor_model,
                    reasoning_effort=settings.auditor_reasoning,
                ),
                ModelRole.RESOLVER: OpenAIModelRoute(
                    model_id=settings.resolver_model,
                    reasoning_effort=settings.resolver_reasoning,
                ),
            },
            connect_timeout_seconds=settings.provider_connect_timeout_seconds,
            read_timeout_seconds=settings.provider_read_timeout_seconds,
            transient_max_retries=settings.provider_max_retries,
            incomplete_max_retries=settings.structured_output_max_retries,
        )
    )


def build_document_ingestor(
    settings: Settings,
) -> DocumentIngestor | ProcessIsolatedDocumentIngestor:
    if settings.parser_isolation_mode == "in_process":
        return DocumentIngestor()
    if hard_process_isolation_supported():
        return ProcessIsolatedDocumentIngestor(
            ParserProcessLimits(
                wall_timeout_seconds=settings.parser_timeout_seconds,
                cpu_time_seconds=settings.parser_cpu_time_seconds,
                address_space_bytes=settings.parser_memory_limit_bytes,
                file_size_bytes=settings.parser_file_size_limit_bytes,
                open_files=settings.parser_open_files_limit,
            )
        )
    if settings.parser_isolation_mode == "process" or settings.environment == "production":
        raise RuntimeError("hard parser process isolation requires a Linux runtime")
    return DocumentIngestor()


def build_observation_sink(settings: Settings) -> ObservationSink:
    sinks: list[ObservationSink] = [JsonLogObservationSink()]
    if settings.otel_endpoint is not None:
        sinks.append(
            build_otlp_http_observation_sink(
                endpoint=settings.otel_endpoint,
                service_name=settings.otel_service_name,
                service_version=__version__,
                environment=settings.environment,
                metric_export_interval_ms=settings.otel_metric_export_interval_ms,
            )
        )
    return CompositeObservationSink(sinks)


def build_service(
    settings: Settings,
    *,
    provider: ModelProvider | None = None,
) -> BriefParserService:
    prompt_dir, pack_dir = runtime_resource_dirs()
    selected_provider = provider or build_model_provider(settings)
    resource_limits = ParseResourceLimits(
        max_sources=settings.max_sources,
        max_total_pdf_pages=settings.max_pages,
        max_total_extracted_chars=settings.max_extracted_chars,
    )
    model_routes = {
        ModelRole.EXTRACTOR: settings.extractor_model,
        ModelRole.AUDITOR: settings.auditor_model,
        ModelRole.RESOLVER: settings.resolver_model,
    }
    pipeline = BriefParsingPipeline(
        selected_provider,
        FilePromptRepository(prompt_dir),
        model_routes=model_routes,
        provider_max_concurrency=settings.provider_max_concurrency,
        job_token_budget=settings.job_token_budget,
        observer=build_observation_sink(settings),
        resource_limits=resource_limits,
        ingestor=build_document_ingestor(settings),
    )
    catalog = DomainPackCatalog(build_domain_pack_loader().load_directory(pack_dir))
    security = FileSecurityValidator(
        InputSecurityPolicy(
            max_file_bytes=settings.max_file_bytes,
            max_pages=settings.max_pages,
            max_extracted_chars=settings.max_extracted_chars,
        )
    )
    return BriefParserService(
        pipeline,
        catalog,
        security=security,
        resource_limits=resource_limits,
    )
