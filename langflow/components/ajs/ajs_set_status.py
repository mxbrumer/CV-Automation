"""AJS Set Status: POST /tools/postings/{id}/status (side statuses such as unsupported_language)."""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, DropdownInput, MessageTextInput, Output, SecretStrInput, StrInput
from lfx.schema.message import Message


class AjsSetStatus(Component):
    display_name = "AJS Set Status"
    description = "Set a posting status through the backend tool endpoint and report the result."
    name = "AjsSetStatus"
    icon = "flag"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        DropdownInput(
            name="to",
            display_name="Status",
            options=["unsupported_language", "needs_manual_text", "error", "new"],
            value="unsupported_language",
        ),
        MessageTextInput(name="note", display_name="Note", value="", advanced=True),
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

    outputs = [Output(display_name="Result", name="result", method="set_status")]

    async def set_status(self) -> Message:
        data = self.posting.data
        posting_id = int(data["posting_id"])
        note = self.note or f"language={data.get('language')} ({data.get('language_method')})"
        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as client:
            response = await client.post(
                f"{self.backend_url.rstrip('/')}/tools/postings/{posting_id}/status",
                json={"to": self.to, "note": note},
            )
            response.raise_for_status()
        result = response.json()
        result["language"] = data.get("language")
        return Message(text=json.dumps(result))
