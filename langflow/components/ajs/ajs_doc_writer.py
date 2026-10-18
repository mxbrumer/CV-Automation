"""AJS Doc Writer: one writer step (brief steps 12-14) for the CV, the cover letter or the email.

Calls the writer model (LLM_WRITER_MODEL) directly on Ollama `/api/chat` with thinking off and
free text output. Every document is English (A2). Deterministic checks run on each answer and a
failed check triggers a retry that names the problem (temperature 0.7, 0.5, 0.3):
  - no `{{ }}` or HTML comment may be left;
  - the CV must keep every role heading of cv.md (no invented or dropped employers);
  - the letter is 200-450 words; the email body is at most 170 words (the template alone is ~135).
The email writer also gets the finished cover letter, so the email reuses its hook and evidence.
The email subject line is built here, not by the model.
"""

import re
from datetime import datetime

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, DropdownInput, MultilineInput, Output, StrInput
from lfx.schema.data import Data

TEMPERATURES = (0.7, 0.5, 0.3)
MAX_OUTPUT_TOKENS = 4000
EMAIL_MAX_WORDS = 170
LETTER_WORDS = (200, 450)
COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)
FENCE = re.compile(r"^```[a-z]*\n(.*)\n```$", re.DOTALL)


def clean(text: str) -> str:
    text = text.strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    return COMMENT.sub("", text).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def role_headings(cv_markdown: str) -> list[str]:
    return [line[4:].strip() for line in cv_markdown.splitlines() if line.startswith("### ")]


def problems(kind: str, text: str, cv_markdown: str) -> list[str]:
    found = []
    if "{{" in text or "}}" in text:
        found.append("placeholders in {{ }} are still in the text; replace every one with real content")
    if "<!--" in text:
        found.append("remove all HTML comments")
    if not text:
        found.append("the answer is empty")
    if kind == "cv":
        missing = [h for h in role_headings(cv_markdown) if h not in text]
        if missing:
            found.append("keep every role heading of the CV exactly as written; missing: " + "; ".join(missing))
    elif kind == "cover_letter":
        count = word_count(text)
        if not LETTER_WORDS[0] <= count <= LETTER_WORDS[1]:
            found.append(f"the letter has {count} words; it must have {LETTER_WORDS[0]} to {LETTER_WORDS[1]}")
    elif kind == "recruiter_email" and word_count(text) > EMAIL_MAX_WORDS:
        found.append(f"the email has {word_count(text)} words; shorten it to at most {EMAIL_MAX_WORDS}")
    return found


def evidence_text(evidence: list[dict]) -> str:
    return "\n".join(f"- [{e['role']} | {e['dates']}] {e['text']}" for e in evidence)


def brief_text(brief: dict) -> str:
    keys = ("title", "company", "must_have", "nice_to_have", "keywords", "company_values", "location")
    return "\n".join(f"{k}: {brief.get(k)}" for k in keys if brief.get(k))


def user_message(kind: str, data: dict, today: str) -> str:
    brief = brief_text(data["job_brief"])
    evidence = evidence_text(data.get("evidence", []))
    recruiter = data.get("recruiter_name") or "none (use the generic greeting)"
    if kind == "cv":
        return f"JOB BRIEF\n{brief}\n\nPRIORITY EVIDENCE (bullets that match the requirements best)\n{evidence}\n\nCV\n{data['cv_markdown']}"
    template = COMMENT.sub("", data["templates"][kind]).strip()
    message = (
        f"TODAY: {today}\nROLE: {data['title']}\nCOMPANY: {data['company']}\nRECRUITER NAME: {recruiter}\n\n"
        f"JOB BRIEF\n{brief}\n\nEVIDENCE FROM THE CV\n{evidence}\n\n"
    )
    if kind == "recruiter_email":
        letter = data.get("documents", {}).get("cover_letter")
        if not letter:
            msg = "the recruiter email needs the cover letter; run the letter writer first"
            raise ValueError(msg)
        message += f"COVER LETTER\n{letter}\n\n"
    return message + f"TEMPLATE\n{template}"


class AjsDocWriter(Component):
    display_name = "AJS Doc Writer"
    description = "Write the tailored CV, cover letter or recruiter email with the writer model (English only)."
    name = "AjsDocWriter"
    icon = "pen-line"

    inputs = [
        DataInput(name="posting", display_name="Posting", input_types=["Data"]),
        DropdownInput(name="kind", display_name="Document", options=["cv", "cover_letter", "recruiter_email"], value="cv"),
        MultilineInput(
            name="system_prompt",
            display_name="System prompt",
            info="Mirrored in langflow/prompts/writer_*.md.",
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
            info="Global variable LLM_WRITER_MODEL (never hard-coded).",
            value="LLM_WRITER_MODEL",
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

    outputs = [Output(display_name="Posting", name="posting_out", method="write")]

    async def _ask(self, client: httpx.AsyncClient, messages: list[dict], temperature: float) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature, "num_predict": MAX_OUTPUT_TOKENS},
        }
        response = await client.post(f"{self.ollama_base_url.rstrip('/')}/api/chat", json=body)
        response.raise_for_status()
        return clean(response.json()["message"]["content"])

    async def write(self) -> Data:
        data = dict(self.posting.data)
        kind = self.kind
        now = datetime.now()  # noqa: DTZ005 - the letter shows the local date
        today = f"{now.day} {now:%B %Y}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message(kind, data, today)},
        ]
        text, issues = "", ["not run"]
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            for temperature in TEMPERATURES:
                text = await self._ask(client, messages, temperature)
                issues = problems(kind, text, data["cv_markdown"])
                if not issues:
                    break
                messages = messages[:2] + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "Rewrite the full document and fix: " + "; ".join(issues) + "."},
                ]
        if issues:
            msg = f"{kind} failed its checks after {len(TEMPERATURES)} attempts: {'; '.join(issues)}"
            raise ValueError(msg)
        if kind == "recruiter_email":
            text = f"Subject: Application for {data['title']} at {data['company']}\n\n{text}"
        documents = dict(data.get("documents", {}))
        documents[kind] = text
        data["documents"] = documents
        self.status = f"{kind}: {word_count(text)} words"
        return Data(data=data)
