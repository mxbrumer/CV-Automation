"""AJS Rubric Score: Gemma rates each requirement against the CV as met / partial / missing.

D10: only skills, experience and domain count. Language, location and work-permit items are
dropped before scoring (they are flags in job_brief). must_have counts twice as much as
nice_to_have. Plan 04 settings: thinking on at temperature 0.3, output capped at 3072 tokens,
one retry with thinking off when the cap is hit; `format` is a schema built for this call.
"""

import json
import re

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, MultilineInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data

THINK_TEMPERATURE = 0.3
THINK_MAX_TOKENS = 3072
PLAIN_MAX_TOKENS = 2048
WEIGHT = {"must_have": 2.0, "nice_to_have": 1.0}
CREDIT = {"met": 1.0, "partial": 0.5, "missing": 0.0}
# Requirements about spoken languages, location or permits are flags, never scored (D10).
NOT_SCORED = re.compile(
    r"\b(danish|dansk|english|engelsk|german|tysk|swedish|svensk|norwegian|norsk|fluent|"
    r"language skills|spoken|sprog|sprogkundskaber|work permit|arbejdstilladelse|located|based in|"
    r"relocat\w*|on-?site|commut\w*|bopæl)\b",
    re.IGNORECASE,
)
MAX_RATIONALE_WORDS = 80


def clip_words(text: str, limit: int) -> str:
    words = text.split()
    return text.strip() if len(words) <= limit else " ".join(words[:limit]).rstrip(".,;") + "..."


class AjsRubricScore(Component):
    display_name = "AJS Rubric Score"
    description = "Rate must_have / nice_to_have against CV evidence with Gemma (weighted %, 0-100)."
    name = "AjsRubricScore"
    icon = "list-checks"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        MultilineInput(
            name="system_prompt",
            display_name="System prompt",
            info="Mirrored in langflow/prompts/matcher_rubric.md.",
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

    outputs = [Output(display_name="Posting", name="posting_out", method="score")]

    async def _ask(self, client, messages, schema, *, think: bool) -> dict | None:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": think,
            "format": schema,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": THINK_TEMPERATURE,
                "num_predict": THINK_MAX_TOKENS if think else PLAIN_MAX_TOKENS,
            },
        }
        response = await client.post(f"{self.ollama_base_url.rstrip('/')}/api/chat", json=body)
        response.raise_for_status()
        payload = response.json()
        if payload.get("done_reason") == "length":
            return None
        try:
            return json.loads(payload["message"]["content"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    async def score(self) -> Data:
        data = dict(self.posting.data)
        brief = data["job_brief"]
        requirements: list[dict] = []
        dropped: list[str] = []
        for kind in ("must_have", "nice_to_have"):
            for index, text in enumerate(brief.get(kind) or [], start=1):
                if NOT_SCORED.search(text):
                    dropped.append(text)
                else:
                    requirements.append(
                        {"id": f"{'m' if kind == 'must_have' else 'n'}{index}", "kind": kind, "text": text}
                    )

        if not requirements:
            data.update(rubric_score=50.0, rationale="No scorable requirements were found in the posting.")
            data["rubric_detail"] = {"items": [], "dropped_flags": dropped, "note": "neutral 50, no requirements"}
            self.status = "no scorable requirements, neutral 50"
            return Data(data=data)

        async with httpx.AsyncClient(headers={"X-API-Key": self.backend_api_key}, timeout=30) as backend:
            response = await backend.get(f"{self.backend_url.rstrip('/')}/tools/profile/cv-sections")
            response.raise_for_status()
        sections = response.json()
        section_ids = {s["id"] for s in sections}

        ids = [r["id"] for r in requirements]
        schema = {
            "type": "object",
            "required": ["items", "rationale"],
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": len(ids),
                    "maxItems": len(ids),
                    "items": {
                        "type": "object",
                        "required": ["id", "status", "evidence"],
                        "properties": {
                            "id": {"enum": ids},
                            "status": {"enum": ["met", "partial", "missing"]},
                            "evidence": {"type": "array", "items": {"enum": sorted(section_ids)}},
                        },
                    },
                },
                "rationale": {"type": "string"},
            },
        }
        cv_text = "\n\n".join(f"[{s['id']}]\n{s['markdown']}" for s in sections)
        req_text = "\n".join(f"{r['id']} ({r['kind']}): {r['text']}" for r in requirements)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"JOB TITLE: {brief.get('title')}\n\nREQUIREMENTS\n{req_text}\n\nCV SECTIONS\n{cv_text}",
            },
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(400.0, connect=10.0)) as client:
            result = await self._ask(client, messages, schema, think=True)
            used_think = True
            if result is None:  # capped, or unparseable: one retry with thinking off
                result = await self._ask(client, messages, schema, think=False)
                used_think = False
        if result is None:
            msg = "rubric scoring failed with thinking on and off"
            raise ValueError(msg)

        by_id = {i["id"]: i for i in result.get("items", []) if i.get("id") in ids}
        earned = total = 0.0
        detail = []
        for req in requirements:
            item = by_id.get(req["id"], {})
            status = item.get("status", "missing")
            evidence = [e for e in item.get("evidence", []) if e in section_ids]
            # Claims without a real CV citation do not get full credit.
            if status == "met" and not evidence:
                status = "partial"
            elif status == "partial" and not evidence:
                status = "missing"
            weight = WEIGHT[req["kind"]]
            earned += weight * CREDIT[status]
            total += weight
            detail.append({**req, "status": status, "evidence": evidence})
        rubric = round(100 * earned / total, 2)
        data["rubric_score"] = rubric
        data["rationale"] = clip_words(result.get("rationale", ""), MAX_RATIONALE_WORDS)
        data["rubric_detail"] = {"items": detail, "dropped_flags": dropped, "think": used_think}
        self.status = f"rubric {rubric} (think={used_think}, {len(dropped)} flag item(s) not scored)"
        return Data(data=data)
