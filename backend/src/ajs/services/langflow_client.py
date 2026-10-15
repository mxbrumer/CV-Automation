"""Client for LangFlow's run endpoint (1.12: POST /api/v1/run/{flow_id}, header x-api-key)."""

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from opentelemetry import trace

from ajs.services.egress import egress_hook
from ajs.settings import Settings
from ajs.telemetry import current_trace_id

tracer = trace.get_tracer("ajs.langflow")


class LangflowError(Exception):
    pass


@dataclass(frozen=True)
class FlowRef:
    """Ties a run to its traces: LangFlow tags its spans with `session_id`; `trace_id` is the
    backend span's trace (None when tracing is off)."""

    session_id: str
    trace_id: str | None


def _tag_input(input_value: str, session_id: str, trace_id: str | None) -> str:
    """LangFlow 1.12 neither continues our trace nor shows our session id on its own trace, but
    it records the flow input on the root span. Adding both ids to a JSON object input makes the
    LangFlow trace searchable from the backend span (the flow components ignore unknown keys)."""
    try:
        payload = json.loads(input_value)
    except ValueError:
        return input_value
    if not isinstance(payload, dict):
        return input_value
    payload["ajs_session"] = session_id
    if trace_id:
        payload["ajs_trace_id"] = trace_id
    return json.dumps(payload)


class LangflowClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._flows = {
            "analysis": settings.langflow_analysis_flow_id,
            "generation": settings.langflow_generation_flow_id,
        }
        self._client = client or httpx.Client(
            base_url=settings.langflow_url,
            headers={"x-api-key": settings.langflow_api_key},
            timeout=httpx.Timeout(900.0, connect=10.0),  # a local-LLM run can take minutes
            event_hooks={
                "request": [
                    egress_hook(
                        "langflow", {(urlsplit(settings.langflow_url).hostname or "").lower()}
                    )
                ]
            },
        )

    def flow_id(self, phase: str) -> str:
        flow_id = self._flows.get(phase, "")
        if not flow_id:
            raise LangflowError(f"no LangFlow flow id configured for phase '{phase}'")
        return flow_id

    def run_flow(
        self,
        flow_id: str,
        input_value: str,
        tweaks: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> FlowRef:
        """Run a flow. Every run gets a session id (unless given) so that the LangFlow trace in
        Phoenix can be found from the backend span and the `workflow_run` row."""
        session_id = session_id or f"ajs-{uuid.uuid4().hex[:16]}"
        body: dict[str, Any] = {
            "input_value": input_value,
            "input_type": "chat",
            "output_type": "chat",
            "tweaks": tweaks or {},
            "session_id": session_id,
        }
        with tracer.start_as_current_span("langflow.run") as span:
            span.set_attribute("session.id", session_id)  # OpenInference session attribute
            span.set_attribute("langflow.flow_id", flow_id)
            body["input_value"] = _tag_input(input_value, session_id, current_trace_id())
            try:
                response = self._client.post(f"/api/v1/run/{flow_id}", json=body)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise LangflowError(str(exc)) from exc
            return FlowRef(session_id, current_trace_id())
