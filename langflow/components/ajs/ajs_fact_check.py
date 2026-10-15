"""AJS Fact Check: compares every generated document with cv.md and flags unsupported claims.

Uses the agent model (LLM_AGENT_MODEL, same loaded model, no swap) with thinking off at
temperature 0.2 and a JSON-schema `format`. It never rewrites anything: the claims go into
`warnings`, which AJS Save Generation stores in the posting event note for the review UI.
Claims about the posting or the company are fine; claims about the candidate must be in cv.md.
"""

import json

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, MultilineInput, Output, StrInput
from lfx.schema.data import Data

SCHEMA = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["document", "claim", "reason"],
                "properties": {
                    "document": {"enum": ["cv", "cover_letter", "recruiter_email"]},
                    "claim": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


class AjsFactCheck(Component):
    display_name = "AJS Fact Check"
    description = "Flag claims about the candidate in the generated documents that cv.md does not support."
    name = "AjsFactCheck"
    icon = "shield-check"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        MultilineInput(
            name="system_prompt",
            display_name="System prompt",
            info="Mirrored in langflow/prompts/fact_check.md.",
            value="",
        ),
        StrInput(
            name="ollama_base_url",
            display_name="Ollama base URL",
            info="Global variable OLLAMA_BASE_URL.",
            value="OLLAMA_BASE_URL",
            load_from_db=True,
        ),
        StrInput(
            name="model",
            display_name="Model",
            info="Global variable LLM_AGENT_MODEL (never hard-coded).",
            value="LLM_AGENT_MODEL",
            load_from_db=True,
        ),
        StrInput(
            name="keep_alive",
            display_name="Keep alive",
            info="Global variable LLM_KEEP_ALIVE.",
            value="LLM_KEEP_ALIVE",
            load_from_db=True,
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Posting", name="posting_out", method="check")]

    async def check(self) -> Data:
        data = dict(self.posting.data)
        documents = data["documents"]
        text = "\n\n".join(f"=== DOCUMENT: {kind} ===\n{body}" for kind, body in documents.items())
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"CV (the only source of truth about the candidate)\n{data['cv_markdown']}\n\n{text}"},
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": SCHEMA,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.2, "num_predict": 2000},
        }
        claims: list[dict] | None = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            for _ in range(3):
                response = await client.post(f"{self.ollama_base_url.rstrip('/')}/api/chat", json=body)
                response.raise_for_status()
                try:
                    claims = json.loads(response.json()["message"]["content"])["claims"]
                    break
                except (json.JSONDecodeError, KeyError, TypeError):
                    body["options"]["temperature"] = 0.5
        if claims is None:
            msg = "fact check returned no valid JSON in 3 attempts"
            raise ValueError(msg)
        data["warnings"] = [c for c in claims if c.get("claim")]
        self.status = f"{len(data['warnings'])} warning(s)"
        return Data(data=data)
