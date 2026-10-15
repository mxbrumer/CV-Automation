"""AJS Save Match: PATCH /tools/postings/{id}/match (steps 9-10). The backend decides the status."""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output, SecretStrInput, StrInput
from lfx.schema.message import Message


class AjsSaveMatch(Component):
    display_name = "AJS Save Match"
    description = "Save both scores and the rationale; the backend sets awaiting_match_review or low_match."
    name = "AjsSaveMatch"
    icon = "save"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        StrInput(
            name="backend_url",
            display_name="Backend URL",
            info="Global variable BACKEND_URL (FastAPI base including /api/v1).",
            value="http://backend:8000/api/v1",
        ),
        SecretStrInput(
            name="backend_api_key",
            display_name="Backend API key",
            info="Global variable BACKEND_API_KEY.",
            value="BACKEND_API_KEY",
            load_from_db=True,
        ),
    ]

    outputs = [Output(display_name="Result", name="result", method="save")]

    async def save(self) -> Message:
        data = self.posting.data
        body = {
            "embedding_score": data["embedding_score"],
            "rubric_score": data["rubric_score"],
            "rationale": data["rationale"] or "No rationale given.",
        }
        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as client:
            response = await client.patch(
                f"{self.backend_url.rstrip('/')}/tools/postings/{data['posting_id']}/match",
                json=body,
            )
            response.raise_for_status()
        result = response.json()
        result.update(
            embedding_score=body["embedding_score"],
            rubric_score=body["rubric_score"],
            language=data.get("language"),
        )
        self.status = f"{result['status']} ({result['match_score']})"
        return Message(text=json.dumps(result))
