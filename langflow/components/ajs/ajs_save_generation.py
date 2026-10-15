"""AJS Save Generation: saves the three documents and sets the status `generated` (brief step 15).

Artifacts go through POST /tools/postings/{id}/artifacts (the backend writes the .md and renders
the .pdf). The fact-check warnings go into the event note of the `generating -> generated`
transition as JSON after the prefix "fact-check: ", where the review UI reads them.
"""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output, SecretStrInput, StrInput
from lfx.schema.message import Message

KINDS = ("cv", "cover_letter", "recruiter_email")


class AjsSaveGeneration(Component):
    display_name = "AJS Save Generation"
    description = "Save the generated documents through the backend and mark the posting generated."
    name = "AjsSaveGeneration"
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
        documents = data["documents"]
        missing = [k for k in KINDS if not documents.get(k)]
        if missing:
            msg = f"missing documents: {missing}"
            raise ValueError(msg)
        base = f"{self.backend_url.rstrip('/')}/tools/postings/{data['posting_id']}"
        warnings = data.get("warnings", [])
        note = "fact-check: " + json.dumps(warnings, ensure_ascii=False)
        saved = []
        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=120) as client:
            for kind in KINDS:
                response = await client.post(f"{base}/artifacts", json={"kind": kind, "markdown": documents[kind]})
                response.raise_for_status()
                saved.append(response.json())
            moved = await client.post(f"{base}/status", json={"to": "generated", "note": note[:4000]})
            moved.raise_for_status()
        self.status = f"saved {len(saved)} documents, {len(warnings)} warning(s)"
        return Message(
            text=json.dumps(
                {
                    "posting_id": data["posting_id"],
                    "status": moved.json()["status"],
                    "artifacts": saved,
                    "warnings": warnings,
                    "budget": data.get("budget"),
                },
                default=str,
            )
        )
