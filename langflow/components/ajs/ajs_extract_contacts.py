"""AJS Extract Contacts: regex pre-extract of emails, phones and the text around them.

The hints go into the job-brief prompt, where Gemma confirms the contact's name and role.
"""

import re

from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w/])(?:\+|00)?\d{2}(?:[\s.-]?\d{2}){3,4}(?!\w)")
GENERIC = ("noreply", "no-reply", "donotreply", "privacy", "persondata", "gdpr")
WINDOW = 140
MAX_SNIPPETS = 4


def snippets(text: str, matches: list) -> list[str]:
    out: list[str] = []
    for m in matches:
        start, end = max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)
        snippet = " ".join(text[start:end].split())
        if not any(snippet[:40] in s for s in out):
            out.append(snippet)
        if len(out) >= MAX_SNIPPETS:
            break
    return out


class AjsExtractContacts(Component):
    display_name = "AJS Extract Contacts"
    description = "Regex pre-extract of recruiter emails and phone numbers with surrounding text."
    name = "AjsExtractContacts"
    icon = "contact"

    inputs = [DataInput(name="posting", display_name="Posting", input_types=["Data"])]
    outputs = [Output(display_name="Posting", name="posting_out", method="extract")]

    def extract(self) -> Data:
        data = dict(self.posting.data)
        text = data["posting_text"]
        emails = [m for m in EMAIL.finditer(text) if not any(g in m.group().lower() for g in GENERIC)]
        phones = [m for m in PHONE.finditer(text) if 8 <= len(re.sub(r"\D", "", m.group())) <= 13]
        data["contact_hints"] = {
            "emails": sorted({m.group() for m in emails}),
            "phones": sorted({" ".join(m.group().split()) for m in phones})[:4],
            "snippets": snippets(text, sorted(emails + phones, key=lambda m: m.start())),
        }
        hints = data["contact_hints"]
        self.status = f"{len(hints['emails'])} email(s), {len(hints['phones'])} phone(s)"
        return Data(data=data)
