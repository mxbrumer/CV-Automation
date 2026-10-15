"""Plan 07: RSS parsing, fetch fallback chain, denylist and the pipeline with stubbed flows."""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ajs.db.models import Actor, FactPosting, FeedItem, PostingStatus
from ajs.domain.status import transition
from ajs.services.fetch_posting import FetchResult, PostingFetcher, employer_link, snippet_text
from ajs.services.langflow_client import FlowRef
from ajs.settings import Settings
from ajs.worker.pipeline import FlowError, Pipeline
from ajs.worker.sources.base import RawJob, split_title
from ajs.worker.sources.jobindex_rss import JobindexRssSource, job_id_from_url, parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "jobindex"
LONG_TEXT = (
    "You have experience with data platforms and requirements for analytics. " * 20
).strip()
Handler = Callable[[httpx.Request], httpx.Response]


# -- RSS parsing ------------------------------------------------------------------------


def test_parse_real_feed_decodes_latin1_and_splits_title() -> None:
    jobs = parse_feed((FIXTURES / "feed_real.xml").read_bytes())
    assert len(jobs) == 3
    assert [j.source_job_id for j in jobs] == [j.url.rsplit("/", 1)[1] for j in jobs]
    assert jobs[0].title.startswith("Kommunikationsmedarbejder - kan du få skolefaglighed")
    assert jobs[0].company == "Københavns Professionshøjskole"
    assert (jobs[1].title, jobs[1].company) == ("BI Business Analyst I", "Hamamatsu Photonics")
    assert all(j.source == "jobindex" and "vis-job" in j.url for j in jobs)


def test_parse_synthetic_feed_edge_cases() -> None:
    jobs = parse_feed((FIXTURES / "feed_synthetic.xml").read_bytes())
    assert [j.source_job_id for j in jobs] == ["h9000001", "h9000002"]  # id-less item skipped
    assert (jobs[0].title, jobs[0].company) == ("Data Engineer", "Acme, Inc.")
    assert (jobs[1].title, jobs[1].company) == ("Analytiker uden kommaer", "Københavns Kommune")
    assert isinstance(jobs[0].published_at, datetime)
    assert jobs[1].published_at is None


def test_split_title_uses_last_comma() -> None:
    assert split_title("Senior Analyst, Data, Acme A/S") == ("Senior Analyst, Data", "Acme A/S")
    assert split_title("No comma here") == ("No comma here", "")


def test_job_id_from_url() -> None:
    assert job_id_from_url("https://www.jobindex.dk/vis-job/h1707174?x=1") == "h1707174"
    assert job_id_from_url("https://www.jobindex.dk/jobsoegning?q=x") is None


def test_source_fetches_every_feed_and_dedups_ids() -> None:
    body = (FIXTURES / "feed_synthetic.xml").read_bytes()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    source = JobindexRssSource(
        ["https://a/feed", "https://b/feed"], "ua", httpx.Client(transport=transport)
    )
    assert [j.source_job_id for j in source.fetch()] == ["h9000001", "h9000002"]


# -- fetch fallback chain -----------------------------------------------------------------


def make_fetcher(
    settings: Settings, handler: Handler
) -> tuple[PostingFetcher, list[str], list[float]]:
    seen: list[str] = []
    sleeps: list[float] = []

    def tracking(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(tracking), follow_redirects=True)
    return PostingFetcher(settings, client, sleep=sleeps.append, clock=time.monotonic), seen, sleeps


def page(body: str) -> str:
    return f"<html><body><article><p>{body}</p></article></body></html>"


def ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, text=page(LONG_TEXT))


def redirect_vis_job(target: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.jobindex.dk" and request.url.path.startswith("/vis-job"):
            return httpx.Response(302, headers={"location": target})
        return ok_handler(request)

    return handler


def test_long_snippet_is_used_without_a_request(settings: Settings) -> None:
    fetcher, seen, _ = make_fetcher(settings, ok_handler)
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", f"<p>{LONG_TEXT}</p>")
    assert result.method == "snippet" and result.text and "requirements" in result.text
    assert seen == []


def test_short_snippet_falls_back_to_fetch(settings: Settings) -> None:
    fetcher, seen, _ = make_fetcher(settings, ok_handler)
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "<p>short</p>")
    assert result.method == "fetched" and result.text
    assert result.source_url == "https://www.jobindex.dk/vis-job/h1"  # stayed on jobindex
    assert seen[-1] == "https://www.jobindex.dk/vis-job/h1"


def test_redirect_to_employer_domain_stores_employer_url(settings: Settings) -> None:
    fetcher, _, _ = make_fetcher(settings, redirect_vis_job("https://careers.acme.dk/jobs/42"))
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    assert result.method == "fetched"
    assert result.source_url == "https://careers.acme.dk/jobs/42"


def test_teaser_page_follows_employer_link(settings: Settings) -> None:
    employer = "https://jobs.acme.dk/posting/42"
    teaser = (
        f'<div class="PaidJob"><a href="https://acme.dk/">Acme</a><a href="{employer}">Job</a>'
        f'<a href="{employer}">View job</a><p>Short teaser only.</p></div>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "www.jobindex.dk":
            return httpx.Response(200, text=teaser)
        return httpx.Response(200, text=page(LONG_TEXT))

    fetcher, seen, _ = make_fetcher(settings, handler)
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    assert result.method == "fetched" and result.source_url == employer
    assert employer in seen
    assert employer_link(teaser.replace(f'<a href="{employer}">View job</a>', "")) is None


def test_denylisted_domain_is_not_fetched(settings: Settings) -> None:
    fetcher, seen, _ = make_fetcher(settings, ok_handler)
    result = fetcher.get_text("https://www.linkedin.com/jobs/view/1", "")
    assert result.method == "denylisted" and result.text is None
    assert seen == []


def test_redirect_to_denylisted_domain_is_dropped(settings: Settings) -> None:
    fetcher, _, _ = make_fetcher(settings, redirect_vis_job("https://www.linkedin.com/jobs/1"))
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    assert result.method == "denylisted" and result.text is None
    assert result.source_url == "https://www.jobindex.dk/vis-job/h1"


def test_robots_disallow_blocks_fetch(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /vis-job/\n")
        return httpx.Response(200, text=page(LONG_TEXT))

    fetcher, seen, _ = make_fetcher(settings, handler)
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    assert result.method == "robots" and result.text is None
    assert not any("vis-job" in u for u in seen)


def server_error(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404 if request.url.path == "/robots.txt" else 500)


def short_page(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, text=page("too short"))


@pytest.mark.parametrize(("handler", "method"), [(server_error, "failed"), (short_page, "short")])
def test_failure_or_short_text_gives_no_text(
    settings: Settings, handler: Handler, method: str
) -> None:
    fetcher, _, _ = make_fetcher(settings, handler)
    result = fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    assert result.text is None and result.method == method


def test_requests_to_one_host_are_throttled(settings: Settings) -> None:
    fetcher, _, sleeps = make_fetcher(settings, ok_handler)
    fetcher.get_text("https://www.jobindex.dk/vis-job/h1", "")
    fetcher.get_text("https://www.jobindex.dk/vis-job/h2", "")
    assert sleeps and all(0 < s <= 1.0 for s in sleeps)


def test_snippet_text_strips_html() -> None:
    assert snippet_text("&#x3C;p&#x3E;Hello &amp; welcome&#x3C;/p&#x3E;") == "Hello & welcome"


# -- pipeline with stubbed flows ------------------------------------------------------------


class FakeSource:
    def __init__(self, jobs: list[RawJob]) -> None:
        self.jobs = jobs

    def fetch(self) -> list[RawJob]:
        return list(self.jobs)


class FakeFetcher:
    def __init__(self, text: str | None = "A full posting text.") -> None:
        self.text, self.calls = text, 0

    def get_text(self, url: str, snippet_html: str) -> FetchResult:
        self.calls += 1
        if self.text is None:
            return FetchResult(None, url, "failed", "boom")
        return FetchResult(self.text, url, "fetched")


class FakeFlows:
    """Stands in for LangFlow: moves the posting the way plan 08's flow does."""

    def __init__(
        self, session: Session, outcome: PostingStatus = PostingStatus.AWAITING_MATCH_REVIEW
    ) -> None:
        self.session, self.outcome = session, outcome
        self.runs: list[tuple[str, int]] = []
        self.error: FlowError | None = None
        self.configured = True

    def available(self, phase: str) -> bool:
        return self.configured

    def run(self, phase: str, posting_id: int) -> FlowRef | None:
        self.runs.append((phase, posting_id))
        if self.error is not None:
            raise self.error
        posting = self.session.get(FactPosting, posting_id)
        assert posting is not None
        if phase == "analysis":
            transition(self.session, posting, PostingStatus.ANALYZED, Actor.AGENT)
            transition(self.session, posting, self.outcome, Actor.AGENT)
        else:
            transition(self.session, posting, PostingStatus.GENERATING, Actor.AGENT)
            transition(self.session, posting, PostingStatus.GENERATED, Actor.AGENT)
        self.session.commit()
        return None


def raw(job_id: str, title: str = "Data Analyst", company: str = "Acme A/S") -> RawJob:
    return RawJob(
        source="jobindex",
        source_job_id=job_id,
        url=f"https://www.jobindex.dk/vis-job/{job_id}",
        title=title,
        company=company,
        snippet_html="<p>snippet</p>",
        feed_url="https://feed",
    )


def pipeline(
    db: Session,
    settings: Settings,
    jobs: list[RawJob],
    fetcher: FakeFetcher | None = None,
    flows: FakeFlows | None = None,
) -> tuple[Pipeline, FakeFlows, FakeFetcher]:
    flows = flows or FakeFlows(db)
    fetcher = fetcher or FakeFetcher()
    pipe = Pipeline(db, settings, FakeSource(jobs), fetcher, flows, sleep=lambda s: None)
    return pipe, flows, fetcher


def posting_for(db: Session, job_id: str) -> FactPosting:
    return db.scalars(select(FactPosting).where(FactPosting.source_job_id == job_id)).one()


def test_pipeline_stops_at_awaiting_match_review(db: Session, settings: Settings) -> None:
    pipe, flows, _ = pipeline(db, settings, [raw("t-1")])
    summary = pipe.run_analysis()
    posting = posting_for(db, "t-1")
    assert posting.status is PostingStatus.AWAITING_MATCH_REVIEW
    assert posting.posting_text == "A full posting text."
    assert summary.postings_created == 1 and summary.analyzed == 1
    assert flows.runs == [("analysis", posting.posting_id)]  # generation is not started
    item = db.scalars(select(FeedItem).where(FeedItem.source_job_id == "t-1")).one()
    assert item.processed_at is not None and posting.feed_item_id == item.feed_item_id


def test_pipeline_low_match_is_terminal(db: Session, settings: Settings) -> None:
    flows = FakeFlows(db, outcome=PostingStatus.LOW_MATCH)
    pipe, _, _ = pipeline(db, settings, [raw("t-2")], flows=flows)
    pipe.run_analysis()
    assert posting_for(db, "t-2").status is PostingStatus.LOW_MATCH
    assert [p for p, _ in flows.runs] == ["analysis"]


def test_repoll_adds_no_duplicates(db: Session, settings: Settings) -> None:
    pipe, flows, fetcher = pipeline(db, settings, [raw("t-3")])
    first = pipe.run_analysis()
    second = pipe.run_analysis()
    assert (first.feed_items_new, second.feed_items_new) == (1, 0)
    assert second.postings_created == 0 and fetcher.calls == 1 and len(flows.runs) == 1
    assert len(db.scalars(select(FactPosting).where(FactPosting.source_job_id == "t-3")).all()) == 1


def test_dedup_stops_before_fetch_and_flow(db: Session, settings: Settings) -> None:
    pipe, _, _ = pipeline(db, settings, [raw("t-4")])
    pipe.run_analysis()
    # the same job re-posted under a new jobindex id: similar company and title (A5)
    pipe2, flows2, fetcher2 = pipeline(db, settings, [raw("t-4b")])
    summary = pipe2.run_analysis()
    assert summary.duplicates == 1 and summary.postings_created == 0
    assert fetcher2.calls == 0 and flows2.runs == []
    assert (
        db.scalars(select(FactPosting).where(FactPosting.source_job_id == "t-4b")).first() is None
    )


def test_missing_text_marks_needs_manual_text(db: Session, settings: Settings) -> None:
    pipe, flows, _ = pipeline(db, settings, [raw("t-5")], fetcher=FakeFetcher(text=None))
    summary = pipe.run_analysis()
    assert posting_for(db, "t-5").status is PostingStatus.NEEDS_MANUAL_TEXT
    assert summary.needs_manual_text == 1 and flows.runs == []


def test_transient_flow_error_is_retried_then_recorded(db: Session, settings: Settings) -> None:
    flows = FakeFlows(db)
    flows.error = FlowError("timeout", transient=True)
    pipe, _, _ = pipeline(db, settings, [raw("t-6")], flows=flows)
    summary = pipe.run_analysis()
    assert len(flows.runs) == 3  # first try + 2 retries
    assert posting_for(db, "t-6").status is PostingStatus.ERROR and summary.errors == 1


def test_permanent_flow_error_is_not_retried_and_isolated(db: Session, settings: Settings) -> None:
    flows = FakeFlows(db)
    flows.error = FlowError("bad request", transient=False)
    jobs = [raw("t-7"), raw("t-8", "Other Role", "Other Co")]
    pipe, _, _ = pipeline(db, settings, jobs, flows=flows)
    summary = pipe.run_analysis()
    assert len(flows.runs) == 2  # one try per posting; the first error did not stop the second
    assert posting_for(db, "t-8").status is PostingStatus.ERROR and summary.errors == 2


def test_generation_runs_only_for_matched_postings(db: Session, settings: Settings) -> None:
    jobs = [raw("t-9"), raw("t-10", "Other Role", "Other Co")]
    pipe, flows, _ = pipeline(db, settings, jobs)
    pipe.run_analysis()
    approved = posting_for(db, "t-9")
    transition(db, approved, PostingStatus.MATCHED, Actor.USER)  # gate 1 (D9)
    db.commit()
    summary = pipe.run_generation()
    assert [r for r in flows.runs if r[0] == "generation"] == [("generation", approved.posting_id)]
    assert summary.generated == 1
    assert posting_for(db, "t-10").status is PostingStatus.AWAITING_MATCH_REVIEW


def test_unconfigured_flow_leaves_postings_new(db: Session, settings: Settings) -> None:
    flows = FakeFlows(db)
    flows.configured = False
    pipe, _, _ = pipeline(db, settings, [raw("t-11")], flows=flows)
    summary = pipe.run_analysis()
    assert posting_for(db, "t-11").status is PostingStatus.NEW and flows.runs == []
    assert summary.notes
