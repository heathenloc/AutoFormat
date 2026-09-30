import json
import logging

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from brief_parser.adapters.observability import (
    CompositeObservationSink,
    JsonLogObservationSink,
    OpenTelemetryObservationSink,
)
from brief_parser.domain.enums import ModelRole, Readiness
from brief_parser.domain.pipeline import ProviderCallRecord, StageRecord
from brief_parser.ports.observability import PipelineObservation


def _observation() -> PipelineObservation:
    return PipelineObservation(
        trace_id="trace_observation",
        request_id="req_observation",
        duration_ms=25,
        readiness=Readiness.INCOMPLETE,
        clause_count=2,
        stages=[
            StageRecord(
                stage="extractor",
                status="completed",
                duration_ms=10,
                item_count=1,
                reason_code="job_token_budget_exceeded",
            )
        ],
        provider_calls=[
            ProviderCallRecord(
                role=ModelRole.EXTRACTOR,
                provider_alias="synthetic",
                model_id="synthetic-model",
                provider_request_id="provider-request-1",
                completion_status="completed",
                input_tokens=40,
                output_tokens=20,
                latency_ms=9,
                retry_count=0,
            )
        ],
        readiness_reason_codes=["job_token_budget_exceeded"],
    )


def test_json_log_sink_emits_only_allowlisted_operational_metadata(caplog) -> None:  # type: ignore[no-untyped-def]
    logger_name = "brief_parser.test.observability"
    caplog.set_level(logging.INFO, logger=logger_name)

    JsonLogObservationSink(logging.getLogger(logger_name)).record_pipeline(_observation())

    payloads = [json.loads(record.getMessage()) for record in caplog.records]
    assert [payload["event"] for payload in payloads] == [
        "brief_parser.stage.complete",
        "brief_parser.provider.complete",
        "brief_parser.pipeline.complete",
    ]
    serialized = json.dumps(payloads, ensure_ascii=False)
    assert "source_text" not in serialized
    assert "filename" not in serialized
    assert "prompt" not in serialized
    assert "response" not in serialized


def test_observation_contract_rejects_content_fields() -> None:
    payload = _observation().model_dump(mode="python")
    payload["source_text"] = "must never be logged"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PipelineObservation.model_validate(payload)


def test_opentelemetry_sink_emits_content_free_span_events_and_metrics() -> None:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    sink = OpenTelemetryObservationSink(
        tracer_provider.get_tracer("brief-parser-test"),
        meter_provider.get_meter("brief-parser-test"),
    )

    sink.record_pipeline(_observation())

    spans = span_exporter.get_finished_spans()
    spans_by_name = {span.name: span for span in spans}
    assert set(spans_by_name) == {
        "brief_parser.pipeline",
        "brief_parser.stage",
        "brief_parser.provider",
    }
    root = spans_by_name["brief_parser.pipeline"]
    assert [event.name for event in spans_by_name["brief_parser.stage"].events] == [
        "brief_parser.stage.complete"
    ]
    assert [event.name for event in spans_by_name["brief_parser.provider"].events] == [
        "brief_parser.provider.complete"
    ]
    assert spans_by_name["brief_parser.stage"].parent is not None
    assert spans_by_name["brief_parser.stage"].parent.span_id == root.context.span_id
    assert spans_by_name["brief_parser.provider"].parent is not None
    assert spans_by_name["brief_parser.provider"].parent.span_id == root.context.span_id
    metrics = metric_reader.get_metrics_data()
    metric_names = {
        metric.name
        for resource_metric in metrics.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
    }
    assert {
        "brief_parser.pipeline.count",
        "brief_parser.pipeline.duration",
        "brief_parser.stage.duration",
        "brief_parser.provider.latency",
        "brief_parser.provider.tokens",
    } <= metric_names
    serialized = repr((spans, metrics))
    assert "source_text" not in serialized
    assert "filename" not in serialized
    assert "prompt" not in serialized
    assert "response" not in serialized
    tracer_provider.shutdown()
    meter_provider.shutdown()


class _FailingObservationSink:
    def record_pipeline(self, observation: PipelineObservation) -> None:
        del observation
        raise RuntimeError("synthetic exporter failure")


class _RecordingObservationSink:
    def __init__(self) -> None:
        self.recorded = False

    def record_pipeline(self, observation: PipelineObservation) -> None:
        del observation
        self.recorded = True


def test_composite_sink_is_fail_open(caplog) -> None:  # type: ignore[no-untyped-def]
    recording = _RecordingObservationSink()
    caplog.set_level(logging.ERROR, logger="brief_parser.observability")
    sink = CompositeObservationSink([_FailingObservationSink(), recording])

    sink.record_pipeline(_observation())

    assert recording.recorded is True
    assert "observation sink failed" in caplog.text
