"""Pipeline orchestrator (architecture §5). Imports only the `JobSource` interface (D3)."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ajs.db.models import Actor, FactPosting, FeedItem, PostingStatus, WorkflowRun
from ajs.domain.status import transition
from ajs.services import postings
from ajs.services.fetch_posting import FetchResult
from ajs.services.langflow_client import FlowRef, LangflowClient, LangflowError
from ajs.settings import Settings
from ajs.worker.sources.base import JobSource, RawJob, split_title

log = logging.getLogger(__name__)

MAX_RETRIES = 2  # extra attempts for transient flow errors


class FlowError(Exception):
    """A flow run failed. `transient` errors (timeouts, 5xx) are retried."""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class TextFetcher(Protocol):
    def get_text(self, url: str, snippet_html: str) -> FetchResult: ...


class FlowRunner(Protocol):
    def available(self, phase: str) -> bool: ...

    def run(self, phase: str, posting_id: int) -> FlowRef | None: ...


class LangflowFlowRunner:
    """Runs the analysis / generation flow for one posting through LangFlow (plans 08, 09)."""

    def __init__(self, client: LangflowClient) -> None:
        self._client = client

    def available(self, phase: str) -> bool:
        try:
            self._client.flow_id(phase)
        except LangflowError:
            return False
        return True

    def run(self, phase: str, posting_id: int) -> FlowRef | None:
        try:
            return self._client.run_flow(
                self._client.flow_id(phase), json.dumps({"posting_id": posting_id})
            )
        except LangflowError as exc:
            cause = exc.__cause__
            transient = isinstance(cause, httpx.TransportError) or (
                isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code >= 500
            )
            raise FlowError(str(exc), transient=transient) from exc


@dataclass
class RunSummary:
    feed_items_new: int = 0
    postings_created: int = 0
    duplicates: int = 0
    needs_manual_text: int = 0
    analyzed: int = 0
    generated: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        source: JobSource,
        fetcher: TextFetcher,
        flows: FlowRunner,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._s, self._settings = session, settings
        self._source, self._fetcher, self._flows = source, fetcher, flows
        self._sleep = sleep

    # -- analysis phase: steps 1-10 -------------------------------------------------------

    def run_analysis(self) -> RunSummary:
        summary = RunSummary()
        self.store_feed_items(self._source.fetch(), summary)
        pending = self._s.scalars(
            select(FeedItem).where(FeedItem.processed_at.is_(None)).order_by(FeedItem.feed_item_id)
        ).all()
        for item in pending:
            try:
                self.intake_item(item, summary)
            except Exception as exc:  # isolate each job
                self._s.rollback()
                log.exception("intake failed for %s", item.source_job_id)
                summary.errors += 1
                summary.notes.append(f"{item.source_job_id}: {exc}")
        self.analyze_pending(summary)
        return summary

    def store_feed_items(self, jobs: list[RawJob], summary: RunSummary) -> None:
        """Idempotent upsert on (source, source_job_id): repeats are skipped."""
        for job in jobs:
            result = self._s.execute(
                insert(FeedItem)
                .values(
                    source=job.source,
                    source_job_id=job.source_job_id,
                    feed_url=job.feed_url,
                    title=f"{job.title}, {job.company}" if job.company else job.title,
                    link=job.url,
                    description_html=job.snippet_html,
                    published_at=job.published_at,
                )
                .on_conflict_do_nothing(constraint="uq_feed_item_source_job")
                .returning(FeedItem.feed_item_id)
            )
            summary.feed_items_new += len(result.all())
        self._s.commit()

    def intake_item(self, item: FeedItem, summary: RunSummary) -> None:
        """Dedup (A5), create the posting row and get its text. processed_at comes last."""
        title, company = split_title(item.title, item.description_html or "")
        company = company or "Unknown company"
        existing, why = postings.find_duplicate(
            self._s,
            self._settings,
            company=company,
            title=title,
            source=item.source,
            source_job_id=item.source_job_id,
        )
        if existing is not None:
            log.info("duplicate of posting %s (%s): %s", existing.posting_id, why, item.title)
            summary.duplicates += 1
            self._finish_item(item)
            return

        try:
            posting = postings.create_posting(
                self._s,
                company=company,
                title=title,
                source=item.source,
                source_job_id=item.source_job_id,
                feed_item_id=item.feed_item_id,
            )
        except postings.Conflict:
            summary.duplicates += 1
            self._finish_item(item)
            return
        summary.postings_created += 1

        result = self._fetcher.get_text(item.link, item.description_html or "")
        self._apply_fetch(posting, result, summary)
        self._finish_item(item)

    def _apply_fetch(self, posting: FactPosting, result: FetchResult, summary: RunSummary) -> None:
        if result.text is None:
            note = f"{result.method}: {result.detail}".rstrip(": ")
            transition(self._s, posting, PostingStatus.NEEDS_MANUAL_TEXT, Actor.SYSTEM, note)
            summary.needs_manual_text += 1
            return
        posting.posting_text = result.text
        clash = self._s.scalars(
            select(FactPosting).where(
                FactPosting.source_url == result.source_url,
                FactPosting.posting_id != posting.posting_id,
                FactPosting.status != PostingStatus.DUPLICATE,
            )
        ).first()
        if clash is not None:
            note = f"same source url as posting {clash.posting_id}"
            transition(self._s, posting, PostingStatus.DUPLICATE, Actor.SYSTEM, note)
            summary.duplicates += 1
            return
        posting.source_url = result.source_url

    def _finish_item(self, item: FeedItem) -> None:
        item.processed_at = datetime.now(UTC)
        self._s.commit()

    def analyze_pending(self, summary: RunSummary) -> None:
        """Run the analysis flow for every `new` posting that has text (also retries)."""
        if not self._flows.available("analysis"):
            summary.notes.append("analysis flow not configured; postings stay 'new'")
            return
        ids = self._s.scalars(
            select(FactPosting.posting_id)
            .where(FactPosting.status == PostingStatus.NEW, FactPosting.posting_text.is_not(None))
            .order_by(FactPosting.posting_id)
        ).all()
        for posting_id in ids:
            self._run_flow_for(posting_id, "analysis", summary)

    # -- generation phase: steps 11-15 ----------------------------------------------------

    def run_generation(self, posting_id: int | None = None) -> RunSummary:
        """Run the generation flow for postings the user approved at gate 1 (D9)."""
        summary = RunSummary()
        if not self._flows.available("generation"):
            summary.notes.append("generation flow not configured")
            return summary
        query = select(FactPosting.posting_id).where(FactPosting.status == PostingStatus.MATCHED)
        if posting_id is not None:
            query = query.where(FactPosting.posting_id == posting_id)
        for pid in self._s.scalars(query.order_by(FactPosting.posting_id)).all():
            self._run_flow_for(pid, "generation", summary)
        return summary

    # -- shared ---------------------------------------------------------------------------

    def _run_flow_for(self, posting_id: int, phase: str, summary: RunSummary) -> None:
        try:
            self._call_with_retry(phase, posting_id)
            self._s.expire_all()
            posting = postings.get_posting(self._s, posting_id)
            if phase == "analysis":
                if posting.status in (PostingStatus.NEW, PostingStatus.ANALYZED):
                    raise FlowError(f"flow finished but status is still '{posting.status.value}'")
                summary.analyzed += 1
            elif posting.status is PostingStatus.GENERATED:
                summary.generated += 1
        except Exception as exc:
            self._s.rollback()
            log.exception("%s flow failed for posting %s", phase, posting_id)
            summary.errors += 1
            summary.notes.append(f"posting {posting_id}: {exc}")
            posting = postings.get_posting(self._s, posting_id)
            try:
                transition(self._s, posting, PostingStatus.ERROR, Actor.SYSTEM, str(exc)[:500])
            except Exception:  # no edge to `error` from the current status
                self._s.rollback()
            self._s.commit()

    def _call_with_retry(self, phase: str, posting_id: int) -> None:
        """Run the flow, retrying transient errors; each attempt is one `workflow_run` row."""
        for attempt in range(MAX_RETRIES + 1):
            run_id = self._start_run(phase, posting_id)
            try:
                ref = self._flows.run(phase, posting_id)
                self._finish_run(run_id, ref=ref)
                return
            except FlowError as exc:
                self._finish_run(run_id, error=str(exc))
                if not exc.transient or attempt == MAX_RETRIES:
                    raise
                log.warning("transient %s error for %s, retrying: %s", phase, posting_id, exc)
                self._sleep(5.0 * (attempt + 1))
            except Exception as exc:
                self._finish_run(run_id, error=str(exc))
                raise

    def _start_run(self, phase: str, posting_id: int) -> int:
        run = WorkflowRun(
            posting_id=posting_id,
            phase=phase,
            status="running",
            langflow_flow_id=self._settings.langflow_analysis_flow_id
            if phase == "analysis"
            else self._settings.langflow_generation_flow_id,
        )
        self._s.add(run)
        self._s.commit()  # keep the record even if the flow call fails
        return run.run_id

    def _finish_run(
        self, run_id: int, ref: FlowRef | None = None, error: str | None = None
    ) -> None:
        run = self._s.get(WorkflowRun, run_id)
        if run is None:
            return
        run.status = "failed" if error else "succeeded"
        run.error = error[:2000] if error else None
        run.finished_at = datetime.now(UTC)
        if ref is not None:
            run.langflow_run_id, run.phoenix_trace_id = ref.session_id, ref.trace_id
        self._s.commit()
