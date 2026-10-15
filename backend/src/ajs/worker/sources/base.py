"""The intake seam (D3): the pipeline only knows `JobSource` and `RawJob`."""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

_COMPANY_SUFFIXES = {"inc", "ltd", "llc", "gmbh", "plc", "corp"}


@dataclass(frozen=True)
class RawJob:
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    snippet_html: str
    published_at: datetime | None = None
    feed_url: str = ""


class JobSource(Protocol):
    def fetch(self) -> list[RawJob]: ...


def split_title(raw: str, description_html: str = "") -> tuple[str, str]:
    """`"<job title>, <company>"` splits on the LAST ", ". No comma: use the logo ALT text."""
    raw = raw.strip()
    if ", " in raw:
        title, company = raw.rsplit(", ", 1)
        if company.strip().casefold().rstrip(".") in _COMPANY_SUFFIXES and ", " in title:
            title, name = title.rsplit(", ", 1)  # "Acme, Inc." keeps its legal suffix
            company = f"{name}, {company}"
        return title.strip(), company.strip()
    alt = re.search(r'ALT="([^"]*)"', html.unescape(description_html), re.IGNORECASE)
    company = html.unescape(alt.group(1)).strip() if alt else ""
    return raw, company
