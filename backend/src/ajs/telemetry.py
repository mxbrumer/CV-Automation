"""OpenTelemetry export to Phoenix (plan 10).

Backend and worker send spans to the local Phoenix (OTLP over HTTP) in the project `ajs-backend`.
LangFlow has its own tracer and sends to one Phoenix project per flow; the two sides are linked by
the LangFlow `session_id`, which `LangflowClient` sets on every run and records on the span and in
`workflow_run` (LangFlow 1.12 does not continue an incoming trace context).

Spans never carry request bodies or posting text; SQL statements carry bind placeholders only.
"""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy import Engine

from ajs.settings import Settings

log = logging.getLogger(__name__)
PROJECT_ATTRIBUTE = "openinference.project.name"  # how Phoenix picks the project

_configured = False


def setup_telemetry(
    settings: Settings, service: str, app: Any | None = None, engine: Engine | None = None
) -> bool:
    """Install the tracer provider and instrumentations. Returns False when disabled."""
    global _configured
    if not settings.otel_enabled or not settings.phoenix_collector_endpoint:
        return False
    if not _configured:
        resource = Resource.create(
            {"service.name": service, PROJECT_ATTRIBUTE: settings.phoenix_project}
        )
        provider = TracerProvider(resource=resource)
        endpoint = settings.phoenix_collector_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        # Only calls through the instrumented client carry context; LangFlow ignores it, and
        # Ollama is never called from here.
        HTTPXClientInstrumentor().instrument()
        _configured = True
        log.info("tracing to %s (project %s)", endpoint, settings.phoenix_project)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    return True


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
