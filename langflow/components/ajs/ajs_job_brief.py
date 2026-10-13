"""AJS Job Brief: Gemma extracts the job_brief JSON through Ollama structured outputs.

Plan 04 findings baked in: `format` is the JSON schema (never "json"), `think` is always sent
explicitly, temperature 0.2 with retries at 0.5 and 0.8 when the JSON is invalid (5 attempts), and no
`num_ctx` is sent (a different value would reload the model; ajs-gemma sets 32768 itself).
"""

import json
import re

import httpx
from jsonschema import Draft202012Validator
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, MultilineInput, Output, StrInput
from lfx.schema.data import Data

# Gemma 4 on Ollama sometimes ends the JSON early (a dropped token inside an array string, or
# 'token repeat limit'); about 1 in 6 calls on some postings. Each failed attempt is cheap, so retry.
TEMPERATURES = (0.2, 0.5, 0.8, 0.5, 0.8)
MAX_TOKENS = 2048
MAX_POSTING_CHARS = 24000  # about 6-7k tokens; the posting is the only large input


JUNK = re.compile(r"[`{}\[\]]")


def semantic_problems(brief: dict) -> list[str]:
    """Structured output can still emit degenerate strings (seen: a must_have of "```json{ ")."""
    problems = []
    for key in ("must_have", "nice_to_have", "keywords", "company_values"):
        bad = [x for x in brief.get(key, []) if JUNK.search(x) or len(x.strip()) < 2]
        if bad:
            problems.append(f"{key} has junk items {bad[:2]}")
    if not brief.get("must_have"):
        problems.append("must_have is empty")
    return problems


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


class AjsJobBrief(Component):
    display_name = "AJS Job Brief"
    description = "Extract the job_brief JSON (requirements, flags, contact) with Gemma via Ollama."
    name = "AjsJobBrief"
    icon = "brain"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        MultilineInput(
            name="system_prompt",
            display_name="System prompt",
            info="Mirrored in langflow/prompts/analyst_job_brief.md.",
            value="",
        ),
        MultilineInput(
            name="schema_json",
            display_name="Output JSON schema",
            info="Mirrored in langflow/prompts/schemas/job_brief.schema.json.",
            value="{}",
            advanced=True,
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
            info="Global variable LLM_KEEP_ALIVE; the same value on every call.",
            value="LLM_KEEP_ALIVE",
            load_from_db=True,
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Posting", name="posting_out", method="extract")]

    async def extract(self) -> Data:
        data = dict(self.posting.data)
        if data.get("already_analyzed") and data.get("job_brief"):
            self.status = "reused saved job_brief"
            return Data(data=data)

        schema = json.loads(self.schema_json)
        validator = Draft202012Validator(schema)
        hints = data.get("contact_hints") or {}
        user = f"POSTING\n{data['posting_text'][:MAX_POSTING_CHARS]}"
        if hints.get("emails") or hints.get("phones"):
            user += "\n\nCONTACT HINTS (regex): " + json.dumps(
                {k: hints.get(k) for k in ("emails", "phones", "snippets")}, ensure_ascii=False
            )
        messages = [
            {
                "role": "system",
                "content": f"{self.system_prompt}\n\nJSON schema:\n{json.dumps(schema)}",
            },
            {"role": "user", "content": user},
        ]
        errors: list[str] = []
        brief = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            for temperature in TEMPERATURES:
                body = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "keep_alive": self.keep_alive,
                    "options": {"temperature": temperature, "num_predict": MAX_TOKENS},
                }
                response = await client.post(f"{self.ollama_base_url.rstrip('/')}/api/chat", json=body)
                if response.status_code != 200:
                    errors.append(f"t={temperature}: HTTP {response.status_code} {response.text[:200]}")
                    continue
                try:
                    candidate = parse_json(response.json()["message"]["content"])
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"t={temperature}: invalid JSON ({exc})")
                    continue
                problems = [e.message for e in validator.iter_errors(candidate)]
                if not problems:
                    problems = semantic_problems(candidate)
                if problems:
                    errors.append(f"t={temperature}: {problems[:3]}")
                    continue
                brief = candidate
                break
        if brief is None:
            msg = f"job_brief extraction failed at every temperature: {errors}"
            raise ValueError(msg)

        # The pre-check language is authoritative for the stored language.
        brief["language"] = data["language"]
        contact = brief.get("contact") or {}
        data["job_brief"] = brief
        data["recruiter_name"] = contact.get("name")
        data["recruiter_email"] = contact.get("email")
        data["recruiter_phone"] = contact.get("phone")
        self.status = f"must_have {len(brief['must_have'])}, nice_to_have {len(brief['nice_to_have'])}"
        return Data(data=data)
