"""
Pharma Agentic AI — OpenTelemetry Instrumentation.

Sets up distributed tracing, structured logging, and custom metrics
collection. Exports to Azure Monitor for unified observability.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Observability across the entire agent swarm
  - Downstream: Azure Monitor / Application Insights
  - Runtime: Initialized once at agent startup

Performance optimizations:
  - Custom counters: pharma.sessions.created, pharma.tasks.completed/failed
  - Custom histogram: pharma.agent.latency_ms
  - Span enrichment: session_id, pillar, agent_type as custom attributes
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from src.shared.config import get_settings

# ── Custom Metrics (Module-Level Singletons) ──────────────────

_meter: metrics.Meter | None = None


def _get_meter() -> metrics.Meter:
    """Lazy-initialize the global meter."""
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("pharma-agentic-ai", "0.1.0")
    return _meter


class PharmaMetrics:
    """
    Custom OpenTelemetry metrics for the Pharma Agentic AI platform.

    These metrics feed the Admin Dashboard and Azure Monitor dashboards.
    Thread-safe: counters and histograms are inherently thread-safe.
    """

    def __init__(self) -> None:
        meter = _get_meter()

        # Counters
        self.sessions_created = meter.create_counter(
            name="pharma.sessions.created",
            description="Number of query sessions created",
            unit="1",
        )
        self.tasks_completed = meter.create_counter(
            name="pharma.tasks.completed",
            description="Number of agent tasks completed successfully",
            unit="1",
        )
        self.tasks_failed = meter.create_counter(
            name="pharma.tasks.failed",
            description="Number of agent tasks that failed (includes DLQ)",
            unit="1",
        )
        self.circuit_breaker_trips = meter.create_counter(
            name="pharma.circuit_breaker.trips",
            description="Number of times circuit breakers tripped OPEN",
            unit="1",
        )
        self.llm_tokens_used = meter.create_counter(
            name="pharma.llm.tokens_used",
            description="Total LLM tokens consumed",
            unit="tokens",
        )

        # Histograms
        self.agent_latency = meter.create_histogram(
            name="pharma.agent.latency_ms",
            description="Agent task execution latency in milliseconds",
            unit="ms",
        )
        self.llm_latency = meter.create_histogram(
            name="pharma.llm.latency_ms",
            description="LLM API call latency in milliseconds",
            unit="ms",
        )

    def record_session_created(self, attributes: dict[str, str] | None = None) -> None:
        """Increment session creation counter."""
        self.sessions_created.add(1, attributes=attributes or {})

    def record_task_completed(
        self, pillar: str, execution_time_ms: int, agent_type: str = ""
    ) -> None:
        """Record a successful task completion."""
        attrs = {"pillar": pillar, "agent_type": agent_type}
        self.tasks_completed.add(1, attributes=attrs)
        self.agent_latency.record(execution_time_ms, attributes=attrs)

    def record_task_failed(self, pillar: str, agent_type: str = "") -> None:
        """Record a task failure."""
        self.tasks_failed.add(1, attributes={"pillar": pillar, "agent_type": agent_type})

    def record_circuit_breaker_trip(self, agent_type: str) -> None:
        """Record a circuit breaker trip event."""
        self.circuit_breaker_trips.add(1, attributes={"agent_type": agent_type})

    def record_llm_usage(
        self, prompt_tokens: int, completion_tokens: int, model: str = ""
    ) -> None:
        """Record LLM token consumption."""
        total = prompt_tokens + completion_tokens
        self.llm_tokens_used.add(total, attributes={"model": model})

    def record_llm_latency(self, latency_ms: int, model: str = "") -> None:
        """Record LLM API call latency."""
        self.llm_latency.record(latency_ms, attributes={"model": model})


# ── Singleton metrics instance ────────────────────────────────
_pharma_metrics: PharmaMetrics | None = None


def get_pharma_metrics() -> PharmaMetrics:
    """Get or create the singleton PharmaMetrics instance."""
    global _pharma_metrics
    if _pharma_metrics is None:
        _pharma_metrics = PharmaMetrics()
    return _pharma_metrics


# ── Telemetry Setup ───────────────────────────────────────────


def setup_telemetry(service_name: str) -> trace.Tracer:
    """
    Initialize OpenTelemetry tracing, metrics, and structured logging.

    Supports two modes:
      - Azure Monitor (production): `azure-monitor-opentelemetry` SDK
        with Application Insights connection string
      - Generic OTLP (local dev): OTLP exporter → Jaeger/Grafana

    Args:
        service_name: The name of the agent/service (e.g., 'planner-agent').

    Returns:
        A Tracer instance for creating spans.
    """
    settings = get_settings()
    telemetry_cfg = settings.telemetry

    # ── Azure Monitor (production) ────────────────────────
    if telemetry_cfg.use_azure_monitor and telemetry_cfg.application_insights_connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=telemetry_cfg.application_insights_connection_string,
                service_name=service_name,
                service_version="0.1.0",
                # Sampling: 1.0 = 100%, 0.1 = 10%
                sampling_ratio=telemetry_cfg.sampling_ratio,
                # Automatic instrumentation of httpx, fastapi, redis, asyncpg
                enable_live_metrics=True,
            )
            logger.info(
                "Azure Monitor OpenTelemetry configured",
                extra={"service": service_name, "sampling": telemetry_cfg.sampling_ratio},
            )
        except ImportError:
            logger.warning(
                "azure-monitor-opentelemetry not installed — falling back to generic OTLP"
            )
            _setup_generic_otlp(service_name, settings)
        except Exception as e:
            logger.error(
                "Azure Monitor setup failed — falling back to generic OTLP",
                extra={"error": str(e)},
            )
            _setup_generic_otlp(service_name, settings)
    else:
        _setup_generic_otlp(service_name, settings)

    # ── Structured Logging (shared across both modes) ─────
    log_level = getattr(logging, settings.app.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() if settings.app.env == "production"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    return trace.get_tracer(service_name)


def _setup_generic_otlp(service_name: str, settings) -> None:
    """
    Configure generic OTLP tracing and metrics (Jaeger, Grafana, etc.).

    Used in local dev or as fallback when Azure Monitor is unavailable.
    """
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "0.1.0",
        "deployment.environment": settings.app.env,
    })

    # Trace provider
    provider = TracerProvider(resource=resource)
    if settings.app.env == "production":
        otlp_exporter = OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    else:
        import os
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(provider)

    # Metrics provider
    metric_reader = PeriodicExportingMetricReader(
        ConsoleMetricExporter(),
        export_interval_millis=30_000 if settings.app.env == "production" else 60_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)


def instrument_fastapi(app: Any) -> None:
    """
    Instrument a FastAPI application with OpenTelemetry.

    Automatically traces all HTTP requests with latency,
    status codes, and route information.
    """
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(service_name: str) -> trace.Tracer:
    """Get a tracer for the given service name."""
    return trace.get_tracer(service_name)


def enrich_span(
    span: trace.Span,
    session_id: str | None = None,
    pillar: str | None = None,
    agent_type: str | None = None,
    task_id: str | None = None,
) -> None:
    """
    Add business-context attributes to a span for Azure Monitor filtering.

    These attributes allow queries like:
      traces | where customDimensions.pillar == "LEGAL"
    """
    if session_id:
        span.set_attribute("pharma.session_id", session_id)
    if pillar:
        span.set_attribute("pharma.pillar", pillar)
    if agent_type:
        span.set_attribute("pharma.agent_type", agent_type)
    if task_id:
        span.set_attribute("pharma.task_id", task_id)
