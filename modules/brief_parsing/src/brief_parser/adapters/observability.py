"""Dependency-free observability adapters for local and standalone operation."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Tracer

from brief_parser.ports.observability import ObservationSink, PipelineObservation


class NullObservationSink:
    def record_pipeline(self, observation: PipelineObservation) -> None:
        del observation


class JsonLogObservationSink:
    """Emit allowlisted JSON events that never contain source or prompt content."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("brief_parser.observability")

    def record_pipeline(self, observation: PipelineObservation) -> None:
        common = {
            "trace_id": observation.trace_id,
            "request_id": observation.request_id,
        }
        for stage in observation.stages:
            self._emit(
                {
                    "event": "brief_parser.stage.complete",
                    **common,
                    **stage.model_dump(mode="json"),
                }
            )
        for call in observation.provider_calls:
            self._emit(
                {
                    "event": "brief_parser.provider.complete",
                    **common,
                    **call.model_dump(mode="json"),
                }
            )
        self._emit(
            {
                "event": "brief_parser.pipeline.complete",
                **common,
                "duration_ms": observation.duration_ms,
                "readiness": observation.readiness.value,
                "clause_count": observation.clause_count,
                "provider_call_count": len(observation.provider_calls),
                "readiness_reason_codes": observation.readiness_reason_codes,
            }
        )

    def _emit(self, payload: dict[str, object]) -> None:
        self._logger.info(
            "%s",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )


class CompositeObservationSink:
    """Fan out safe observations without allowing telemetry failures to fail a job."""

    def __init__(
        self,
        sinks: Iterable[ObservationSink],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sinks = tuple(sinks)
        if not self._sinks:
            raise ValueError("at least one observation sink is required")
        self._logger = logger or logging.getLogger("brief_parser.observability")

    def record_pipeline(self, observation: PipelineObservation) -> None:
        for sink in self._sinks:
            try:
                sink.record_pipeline(observation)
            except Exception:
                self._logger.error(
                    "observation sink failed: %s",
                    type(sink).__name__,
                )


class OpenTelemetryObservationSink:
    """Create content-free spans and metrics from the allowlisted observation model."""

    def __init__(self, tracer: Tracer, meter: Meter) -> None:
        self._tracer = tracer
        self._pipeline_count = meter.create_counter(
            "brief_parser.pipeline.count",
            unit="{job}",
        )
        self._pipeline_duration = meter.create_histogram(
            "brief_parser.pipeline.duration",
            unit="ms",
        )
        self._stage_duration = meter.create_histogram(
            "brief_parser.stage.duration",
            unit="ms",
        )
        self._provider_latency = meter.create_histogram(
            "brief_parser.provider.latency",
            unit="ms",
        )
        self._provider_tokens = meter.create_counter(
            "brief_parser.provider.tokens",
            unit="{token}",
        )

    def record_pipeline(self, observation: PipelineObservation) -> None:
        pipeline_attributes = {
            "brief_parser.readiness": observation.readiness.value,
        }
        self._pipeline_count.add(1, pipeline_attributes)
        self._pipeline_duration.record(observation.duration_ms, pipeline_attributes)

        with self._tracer.start_as_current_span(
            "brief_parser.pipeline",
            kind=SpanKind.INTERNAL,
            attributes={
                "brief_parser.trace_id": observation.trace_id,
                "brief_parser.request_id": observation.request_id,
                "brief_parser.readiness": observation.readiness.value,
                "brief_parser.duration_ms": observation.duration_ms,
                "brief_parser.clause_count": observation.clause_count,
                "brief_parser.provider_call_count": len(observation.provider_calls),
                "brief_parser.readiness_reason_codes": tuple(
                    observation.readiness_reason_codes
                ),
            },
        ):
            for stage in observation.stages:
                attributes: dict[str, str | int] = {
                    "brief_parser.stage": stage.stage,
                    "brief_parser.stage.status": stage.status,
                    "brief_parser.stage.duration_ms": stage.duration_ms,
                    "brief_parser.stage.item_count": stage.item_count,
                }
                if stage.reason_code is not None:
                    attributes["brief_parser.stage.reason_code"] = stage.reason_code
                with self._tracer.start_as_current_span(
                    "brief_parser.stage",
                    kind=SpanKind.INTERNAL,
                    attributes=attributes,
                ) as stage_span:
                    stage_span.add_event(
                        "brief_parser.stage.complete",
                        attributes=attributes,
                    )
                self._stage_duration.record(
                    stage.duration_ms,
                    {
                        "brief_parser.stage": stage.stage,
                        "brief_parser.stage.status": stage.status,
                    },
                )

            for call in observation.provider_calls:
                provider_attributes: dict[str, str] = {
                    "brief_parser.provider": call.provider_alias,
                    "brief_parser.model": call.model_id,
                    "brief_parser.role": call.role.value,
                    "brief_parser.completion_status": call.completion_status,
                }
                event_attributes: dict[str, str | int] = {
                    **provider_attributes,
                    "brief_parser.input_tokens": call.input_tokens,
                    "brief_parser.output_tokens": call.output_tokens,
                    "brief_parser.latency_ms": call.latency_ms,
                    "brief_parser.retry_count": call.retry_count,
                }
                if call.provider_request_id is not None:
                    event_attributes["brief_parser.provider_request_id"] = (
                        call.provider_request_id
                    )
                with self._tracer.start_as_current_span(
                    "brief_parser.provider",
                    kind=SpanKind.CLIENT,
                    attributes=event_attributes,
                ) as provider_span:
                    provider_span.add_event(
                        "brief_parser.provider.complete",
                        attributes=event_attributes,
                    )
                self._provider_latency.record(call.latency_ms, provider_attributes)
                self._provider_tokens.add(
                    call.input_tokens,
                    {**provider_attributes, "brief_parser.token.type": "input"},
                )
                self._provider_tokens.add(
                    call.output_tokens,
                    {**provider_attributes, "brief_parser.token.type": "output"},
                )


def build_otlp_http_observation_sink(
    *,
    endpoint: str,
    service_name: str,
    service_version: str,
    environment: str,
    metric_export_interval_ms: int,
) -> OpenTelemetryObservationSink:
    """Build an OTLP/HTTP sink whose Collector endpoint remains replaceable."""

    base_endpoint = endpoint.rstrip("/")
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{base_endpoint}/v1/traces"),
        )
    )
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base_endpoint}/v1/metrics"),
        export_interval_millis=metric_export_interval_ms,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    instrumentation_name = "brief_parser.observability"
    return OpenTelemetryObservationSink(
        tracer_provider.get_tracer(instrumentation_name, service_version),
        meter_provider.get_meter(instrumentation_name, service_version),
    )
