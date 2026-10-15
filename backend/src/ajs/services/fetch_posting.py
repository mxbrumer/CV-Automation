"""Get the full posting text (D4): snippet if complete, else fetch + trafilatura, else manual."""

import html
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from ajs.services.egress import egress_hook
from ajs.settings import Settings

_REQUIREMENT_HINTS = re.compile(
    r"\b(krav|kvalifikationer|kompetencer|du har|vi søger|requirements?|qualifications?|"
    r"you have|you are|we are looking|experience|erfaring)\b",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|h\d)[^>]*>", re.IGNORECASE)
JOBINDEX_HOST = "jobindex.dk"
_HREF = re.compile(r'<a [^>]*href="(https?://[^"]+)"', re.IGNORECASE)
_SOCIAL = ("facebook.com", "linkedin.com", "twitter.com", "x.com", "google.com")


def employer_link(page_html: str) -> str | None:
    """The employer's own posting URL on a Jobindex ad page: the external link used most often
    (title and "View job" buttons) inside the ad block. A lone link is the company homepage."""
    start = page_html.find('class="PaidJob')
    links = _HREF.findall(html.unescape(page_html[start:] if start >= 0 else page_html))
    counts = Counter(
        u
        for u in links
        if not _on_domain(_host(u), JOBINDEX_HOST)
        and not any(_on_domain(_host(u), d) for d in _SOCIAL)
    )
    best = counts.most_common(1)
    return best[0][0] if best and best[0][1] >= 2 else None


@dataclass(frozen=True)
class FetchResult:
    text: str | None
    source_url: str  # employer page when we ended up on one, else the vis-job URL
    method: str  # snippet | fetched | denylisted | robots | failed | short
    detail: str = ""


def snippet_text(snippet_html: str) -> str:
    text = _BLOCK.sub("\n", html.unescape(snippet_html))
    text = html.unescape(_TAG.sub(" ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def _words(text: str) -> int:
    return len(text.split())


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


class PostingFetcher:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            headers={"User-Agent": settings.fetch_user_agent},
            timeout=15.0,
            follow_redirects=True,
            event_hooks={"request": [egress_hook("posting fetcher")]},
        )
        self._sleep, self._clock = sleep, clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def _denied(self, host: str) -> bool:
        return any(_on_domain(host, d) for d in self._settings.denylist)

    def _throttle(self, host: str) -> None:
        """At most 1 request/second per host (politeness, plan 07)."""
        last = self._last_request.get(host)
        if last is not None:
            wait = 1.0 - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = None
            try:
                self._throttle(_host(url))
                response = self._client.get(f"{origin}/robots.txt")
                if response.status_code < 400:  # no robots.txt: everything allowed
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(self._settings.fetch_user_agent, url)

    def get_text(self, url: str, snippet_html: str) -> FetchResult:
        snippet = snippet_text(snippet_html)
        if _words(snippet) >= self._settings.fetch_min_snippet_words and _REQUIREMENT_HINTS.search(
            snippet
        ):
            return FetchResult(snippet, url, "snippet")

        host = _host(url)
        if self._denied(host):
            return FetchResult(None, url, "denylisted", host)
        if not self._allowed(url):
            return FetchResult(None, url, "robots", "disallowed by robots.txt")
        try:
            self._throttle(host)
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(None, url, "failed", str(exc))

        final_url = str(response.url)
        final_host = _host(final_url)
        if self._denied(final_host):
            return FetchResult(None, url, "denylisted", final_host)
        employer_url = final_url if not _on_domain(final_host, JOBINDEX_HOST) else url
        text = trafilatura.extract(response.text, url=final_url, favor_recall=True)
        if (not text or _words(text) < self._settings.fetch_min_text_words) and _on_domain(
            final_host, JOBINDEX_HOST
        ):
            return self._follow_employer(url, response.text, text)
        if not text or _words(text) < self._settings.fetch_min_text_words:
            return FetchResult(None, employer_url, "short", f"{_words(text or '')} words")
        return FetchResult(text.strip(), employer_url, "fetched")

    def _follow_employer(self, url: str, page_html: str, teaser: str | None) -> FetchResult:
        """Jobindex shows only a teaser for jobs hosted by the employer: fetch their page."""
        short = FetchResult(None, url, "short", f"{_words(teaser or '')} words")
        target = employer_link(page_html)
        if target is None:
            return short
        host = _host(target)
        if self._denied(host):
            return FetchResult(None, url, "denylisted", host)
        if not self._allowed(target):
            return FetchResult(None, url, "robots", f"{host} disallows")
        try:
            self._throttle(host)
            response = self._client.get(target)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(None, url, "failed", str(exc))
        final_url = str(response.url)
        if self._denied(_host(final_url)):
            return FetchResult(None, url, "denylisted", _host(final_url))
        text = trafilatura.extract(response.text, url=final_url, favor_recall=True)
        if not text or _words(text) < self._settings.fetch_min_text_words:
            return FetchResult(None, url, "short", f"employer page: {_words(text or '')} words")
        return FetchResult(text.strip(), final_url, "fetched", "employer page")
