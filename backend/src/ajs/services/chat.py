"""Chat editing of one generated document (plan 12, A3): the local model revises the whole
Markdown. Called straight from the backend (not LangFlow) for low latency."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ajs.services.egress import egress_hook
from ajs.settings import Settings

SYSTEM_PROMPT = """You revise one job-application document for the candidate, on their request.

Rules:
- Use only facts that appear in the candidate's CV below. Never invent employers, dates, skills,
  numbers or qualifications. If the request needs a fact the CV does not hold, say so in the
  explanation and leave the document unchanged on that point.
- Keep the document's language (English), its Markdown structure and its headings, unless the
  request is about them.
- Return the COMPLETE revised document, not a diff or a fragment.

Answer in exactly this shape:
EXPLANATION: one or two sentences on what you changed (or why you did not).
<document>
the full revised Markdown
</document>

If the user only asks a question, answer after EXPLANATION: and omit the <document> block."""

_DOC = re.compile(r"<document>\s*\n?(.*?)(?:\n?\s*</document>|\Z)", re.DOTALL)
_EXPL = re.compile(r"EXPLANATION:\s*(.*?)\s*(?:<document>|\Z)", re.DOTALL)


@dataclass(frozen=True)
class Reply:
    explanation: str
    markdown: str | None


def parse_reply(raw: str) -> Reply:
    """Split the model's answer into the explanation and the proposed document (if any)."""
    doc = _DOC.search(raw)
    markdown = doc.group(1).strip() if doc else None
    expl = _EXPL.search(raw)
    explanation = expl.group(1).strip() if expl else raw.split("<document>")[0].strip()
    return Reply(explanation or "Done.", markdown or None)


class ChatLLM(Protocol):
    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]: ...


class OllamaChat:
    """Streams `/api/chat` from the local Ollama (the only model endpoint, governance rule)."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._model = settings.llm_agent_model
        self._keep_alive = settings.llm_keep_alive
        host = httpx.URL(settings.ollama_base_url).host
        self._client = client or httpx.Client(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(600.0, connect=10.0),
            event_hooks={"request": [egress_hook("chat editing", only_hosts={host})]},
        )

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "think": False,  # Gemma 4 thinks by default (plan 04); not needed for edits
            "keep_alive": self._keep_alive,
            "options": {"temperature": 0.3},
        }
        with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(str(chunk["error"]))
                if text := chunk.get("message", {}).get("content"):
                    yield text
                if chunk.get("done"):
                    return


def build_messages(
    *,
    kind: str,
    document: str,
    brief: dict[str, Any] | None,
    cv: str | None,
    history: list[tuple[str, str]],
    instruction: str,
) -> list[dict[str, str]]:
    """`history` is (role, content) of earlier turns for this document, oldest first."""
    context = (
        f"Document type: {kind.replace('_', ' ')}\n\n"
        f"Job brief (JSON):\n{json.dumps(brief or {}, ensure_ascii=False, indent=1)}\n\n"
        f"Candidate CV (the only source of facts):\n{cv or '(cv.md is not available)'}\n\n"
        f"Current document:\n<document>\n{document}\n</document>"
    )
    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{context}"}]
    messages += [{"role": role, "content": content} for role, content in history]
    messages.append({"role": "user", "content": instruction})
    return messages
