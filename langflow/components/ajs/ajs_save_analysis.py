"""AJS Save Analysis: PATCH /tools/postings/{id}/analysis (steps 6-8; moves new -> analyzed)."""

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data


class AjsSaveAnalysis(Component):
    display_name = "AJS Save Analysis"
    description = "Save language, recruiter contact and job_brief through the backend."
    name = "AjsSaveAnalysis"
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

    outputs = [Output(display_name="Posting", name="posting_out", method="save")]

    async def save(self) -> Data:
        data = dict(self.posting.data)
        if data.get("already_analyzed"):
            self.status = "already analyzed, skipped"
            return Data(data=data)
        body = {
            "language": data["language"],
            "recruiter_name": data.get("recruiter_name"),
            "recruiter_email": data.get("recruiter_email"),
            "recruiter_phone": data.get("recruiter_phone"),
            "job_brief": data["job_brief"],
        }
        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as client:
            response = await client.patch(
                f"{self.backend_url.rstrip('/')}/tools/postings/{data['posting_id']}/analysis",
                json=body,
            )
            response.raise_for_status()
        data["status"] = response.json()["status"]
        self.status = data["status"]
        return Data(data=data)
