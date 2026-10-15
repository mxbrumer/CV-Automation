"""AJS Load Generation: starts the generation phase for one `matched` posting (brief steps 11-12).

Input is {"posting_id": 12}. The posting must be `matched` (approved at gate 1, D9) or already
`generating` (a retry after a crash). The component loads the posting, the full CV and both
templates from the backend, creates the application folder and moves the status to `generating`.
"""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data
from lfx.schema.message import Message

RUNNABLE = {"matched", "generating"}


class AjsLoadGeneration(Component):
    display_name = "AJS Load Generation"
    description = "Load a matched posting, the CV and the templates; create the folder; set status generating."
    name = "AjsLoadGeneration"
    icon = "download"

    inputs = [
        MessageTextInput(
            name="input_value",
            display_name="Input",
            info='JSON: {"posting_id": int}',
            input_types=["Message"],
        ),
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

    outputs = [
        Output(display_name="Posting", name="posting", method="load"),
        Output(display_name="Skipped", name="skipped", method="skipped"),
    ]

    async def _load(self) -> tuple[dict | None, str | None]:
        cached = getattr(self, "_ajs_result", None)
        if cached is not None:
            return cached
        raw = self.input_value
        raw = raw.text if hasattr(raw, "text") else str(raw or "")
        try:
            payload = {"posting_id": int(raw)} if raw.strip().isdigit() else json.loads(raw)
            posting_id = int(payload["posting_id"])
        except (ValueError, KeyError, TypeError) as exc:
            msg = 'input must be JSON like {"posting_id": 12}'
            raise ValueError(msg) from exc
        base = self.backend_url.rstrip("/")
        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as client:
            response = await client.get(f"{base}/postings/{posting_id}")
            response.raise_for_status()
            detail = response.json()
            if detail["status"] not in RUNNABLE:
                reason = f"posting {posting_id} has status '{detail['status']}', nothing to generate"
                self._ajs_result = (None, reason)
                return self._ajs_result
            if not detail.get("job_brief"):
                msg = f"posting {posting_id} has no job_brief"
                raise ValueError(msg)
            sections = (await client.get(f"{base}/tools/profile/cv-sections")).raise_for_status().json()
            letter = (await client.get(f"{base}/tools/profile/templates/cover_letter")).raise_for_status().json()
            email = (await client.get(f"{base}/tools/profile/templates/recruiter_email")).raise_for_status().json()
            folder = (await client.post(f"{base}/tools/postings/{posting_id}/folder")).raise_for_status().json()
            if detail["status"] == "matched":
                moved = await client.post(
                    f"{base}/tools/postings/{posting_id}/status",
                    json={"to": "generating", "note": "generation started"},
                )
                moved.raise_for_status()
        cv_markdown = "\n\n".join(s["markdown"] for s in sections).strip()
        brief = detail["job_brief"]
        data = {
            "posting_id": posting_id,
            "company": detail["company"],
            "title": detail["title"],
            "job_brief": brief,
            "recruiter_name": detail.get("recruiter_name") or (brief.get("contact") or {}).get("name"),
            "cv_markdown": cv_markdown,
            "templates": {"cover_letter": letter["markdown"], "recruiter_email": email["markdown"]},
            "folder": folder["path"],
            "documents": {},
        }
        self._ajs_result = (data, None)
        return self._ajs_result

    async def load(self) -> Data:
        data, reason = await self._load()
        if data is None:
            self.stop("posting")
            return Data(data={"skipped": reason})
        self.stop("skipped")
        self.status = f"posting {data['posting_id']} generating"
        return Data(data=data)

    async def skipped(self) -> Message:
        data, reason = await self._load()
        if data is not None:
            self.stop("skipped")
            return Message(text="")
        self.stop("posting")
        return Message(text=json.dumps({"skipped": True, "reason": reason}))
