"""Client for LangFlow's run endpoint (1.12: POST /api/v1/run/{flow_id}, header x-api-key)."""

from typing import Any

import httpx

from ajs.settings import Settings


class LangflowError(Exception):
    pass


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
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "input_value": input_value,
            "input_type": "chat",
            "output_type": "chat",
            "tweaks": tweaks or {},
        }
        if session_id:
            body["session_id"] = session_id
        try:
            response = self._client.post(f"/api/v1/run/{flow_id}", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LangflowError(str(exc)) from exc
        result: dict[str, Any] = response.json()
        return result
