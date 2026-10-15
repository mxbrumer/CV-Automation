"""Jobindex RSS source. Feeds are RSS 2.0 in ISO-8859-1; one item is one job."""

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from ajs.services.egress import egress_hook
from ajs.worker.sources.base import RawJob, split_title

SOURCE = "jobindex"
_JOB_ID = re.compile(r"/vis-job/([^/?#]+)")


def job_id_from_url(url: str) -> str | None:
    match = _JOB_ID.search(url)
    return match.group(1) if match else None


def parse_feed(content: bytes, feed_url: str = "") -> list[RawJob]:
    """Parse feed bytes (the XML declaration sets the encoding); items without an id are skipped."""
    root = ET.fromstring(content)
    jobs: list[RawJob] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        job_id = job_id_from_url(link)
        raw_title = (item.findtext("title") or "").strip()
        if not job_id or not raw_title:
            continue
        description = item.findtext("description") or ""
        title, company = split_title(raw_title, description)
        published: datetime | None = None
        if pub := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                published = None
        jobs.append(
            RawJob(
                source=SOURCE,
                source_job_id=job_id,
                url=link,
                title=title,
                company=company,
                snippet_html=description,
                published_at=published,
                feed_url=feed_url,
            )
        )
    return jobs


class JobindexRssSource:
    def __init__(
        self, feed_urls: list[str], user_agent: str, client: httpx.Client | None = None
    ) -> None:
        self._urls = feed_urls
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=15.0,
            follow_redirects=True,
            event_hooks={"request": [egress_hook("jobindex feed")]},
        )

    def fetch(self) -> list[RawJob]:
        jobs: dict[str, RawJob] = {}
        for url in self._urls:
            response = self._client.get(url)
            response.raise_for_status()
            for job in parse_feed(response.content, url):
                jobs.setdefault(job.source_job_id, job)
        return list(jobs.values())
