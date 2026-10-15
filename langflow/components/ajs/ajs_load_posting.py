"""AJS Load Posting: reads the flow input and decides whether this run has anything to do.

Input is the JSON string {"posting_id": 12, "posting_text": "..."} (posting_text is optional;
the backend copy is used when it is missing). The posting must be `new` or `analyzed` (a retry),
or `error` (reset to `new` first), so a run is idempotent and retryable (one run per job).
"""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data
from lfx.schema.message import Message

RUNNABLE = {"new", "analyzed", "error"}


class AjsLoadPosting(Component):
    display_name = "AJS Load Posting"
    description = "Parse the flow input, fetch the posting from the backend and check its status."
    name = "AjsLoadPosting"
    icon = "download"

    inputs = [
        MessageTextInput(
            name="input_value",
            display_name="Input",
            info='JSON: {"posting_id": int, "posting_text": str (optional)}',
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
        Output(display_name="Posting", name="posting", method="load_posting"),
        Output(display_name="Skipped", name="skipped", method="skipped"),
    ]

    async def _load(self) -> tuple[dict | None, str | None]:
        cached = getattr(self, "_ajs_result", None)
        if cached is not None:
            return cached
        raw = self.input_value
        raw = raw.text if hasattr(raw, "text") else str(raw or "")
        try:
            # The backend sends {"posting_id": 12}; a bare id such as "12" is accepted too.
            payload = {"posting_id": int(raw)} if raw.strip().isdigit() else json.loads(raw)
            posting_id = int(payload["posting_id"])
        except (ValueError, KeyError, TypeError) as exc:
            msg = 'input must be JSON like {"posting_id": 12, "posting_text": "..."}'
            raise ValueError(msg) from exc
        headers = {"X-API-Key": self.backend_api_key}
        base = self.backend_url.rstrip("/")
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            response = await client.get(f"{base}/postings/{posting_id}")
            response.raise_for_status()
            detail = response.json()
            status = detail["status"]
            if status not in RUNNABLE:
                result = (None, f"posting {posting_id} has status '{status}', nothing to analyze")
                self._ajs_result = result
                return result
            if status == "error":
                reset = await client.post(
                    f"{base}/tools/postings/{posting_id}/status",
                    json={"to": "new", "note": "retry analysis"},
                )
                reset.raise_for_status()
                status = "new"
        text = (payload.get("posting_text") or detail.get("posting_text") or "").strip()
        if not text:
            msg = f"posting {posting_id} has no text; set needs_manual_text in the caller"
            raise ValueError(msg)
        data = {
            "posting_id": posting_id,
            "posting_text": text,
            "company": detail["company"],
            "title": detail["title"],
            "status": status,
            "already_analyzed": status == "analyzed" and bool(detail.get("job_brief")),
        }
        if data["already_analyzed"]:
            data["job_brief"] = detail["job_brief"]
            data["language"] = detail.get("posting_language") or detail["job_brief"].get("language")
        self._ajs_result = (data, None)
        return self._ajs_result

    async def load_posting(self) -> Data:
        data, reason = await self._load()
        if data is None:
            self.stop("posting")
            return Data(data={"skipped": reason})
        self.stop("skipped")
        self.status = f"posting {data['posting_id']} ({data['status']})"
        return Data(data=data)

    async def skipped(self) -> Message:
        data, reason = await self._load()
        if data is not None:
            self.stop("skipped")
            return Message(text="")
        self.stop("posting")
        return Message(text=json.dumps({"skipped": True, "reason": reason}))
