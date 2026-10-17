"""Pipeline runner (architecture §5): analysis for `new` postings, generation for `matched` ones.

Started in the background after an Add job submit, a gate-1 approval and Process pending (D3).
One run at a time, guarded by a Postgres advisory lock.
"""

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from ajs.db.models import Actor, FactPosting, PostingStatus, WorkflowRun
from ajs.db.session import get_engine
from ajs.domain.status import transition
from ajs.services import postings
from ajs.services.langflow_client import FlowRef, LangflowClient, LangflowError
from ajs.settings import Settings

log = logging.getLogger(__name__)

MAX_RETRIES = 2  # extra attempts for transient flow errors
LOCK_KEY = 70_707_001  # pg advisory lock: one pipeline run at a time


class FlowError(Exception):
    """A flow run failed. `transient` errors (timeouts, 5xx) are retried."""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


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
    flow_runs: int = 0  # postings sent to a flow, whatever the outcome
    analyzed: int = 0
    generated: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, other: "RunSummary") -> None:
        self.flow_runs += other.flow_runs
        self.analyzed += other.analyzed
        self.generated += other.generated
        self.errors += other.errors
        self.notes += other.notes


class Pipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        flows: FlowRunner,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._s, self._settings, self._flows = session, settings, flows
        self._sleep = sleep

    def run_all(self) -> RunSummary:
        """Drafts for approved matches first, then analysis, until nothing is pending.

        Every trigger (Add job, gate-1 approval, Process pending) starts this same run, and a
        trigger that finds the lock taken is skipped, so the running one must pick up whatever
        arrived meanwhile in either phase.
        """
        total = RunSummary()
        while True:
            step = self.run_generation()
            step.add(self.analyze_pending())
            total.add(step)
            if step.flow_runs == 0:
                return total

    # -- analysis phase: steps 6-10 -------------------------------------------------------

    def analyze_pending(self) -> RunSummary:
        """Run the analysis flow for every `new` posting that has text (also retries).

        Re-queries until nothing is left, so a job submitted while this run holds the lock
        (its own run was skipped) is analyzed too. Each posting is tried once per call.
        """
        summary = RunSummary()
        if not self._flows.available("analysis"):
            summary.notes.append("analysis flow not configured; postings stay 'new'")
            return summary
        tried: set[int] = set()
        while True:
            ids = [
                pid
                for pid in self._s.scalars(
                    select(FactPosting.posting_id)
                    .where(
                        FactPosting.status == PostingStatus.NEW,
                        FactPosting.posting_text.is_not(None),
                    )
                    .order_by(FactPosting.posting_id)
                ).all()
                if pid not in tried
            ]
            if not ids:
                return summary
            for posting_id in ids:
                tried.add(posting_id)
                self._run_flow_for(posting_id, "analysis", summary)

    # -- generation phase: steps 11-15 ----------------------------------------------------

    def run_generation(self) -> RunSummary:
        """Run the generation flow for postings the user approved at gate 1 (D9)."""
        summary = RunSummary()
        if not self._flows.available("generation"):
            summary.notes.append("generation flow not configured")
            return summary
        query = select(FactPosting.posting_id).where(FactPosting.status == PostingStatus.MATCHED)
        for pid in self._s.scalars(query.order_by(FactPosting.posting_id)).all():
            self._run_flow_for(pid, "generation", summary)
        return summary

    # -- shared ---------------------------------------------------------------------------

    def _run_flow_for(self, posting_id: int, phase: str, summary: RunSummary) -> None:
        summary.flow_runs += 1
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


@contextmanager
def advisory_lock(engine: Engine) -> Iterator[bool]:
    """Hold a session-level Postgres advisory lock on a dedicated connection."""
    with engine.connect() as conn:
        acquired = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.commit()


def run_once(settings: Settings) -> RunSummary | None:
    """One locked run of everything pending (`Pipeline.run_all`); skipped if one is running."""
    engine = get_engine()
    with advisory_lock(engine) as acquired:
        if not acquired:
            log.info("another pipeline run holds the lock; skipping")
            return None
        with Session(engine) as session:
            pipeline = Pipeline(session, settings, LangflowFlowRunner(LangflowClient(settings)))
            summary = pipeline.run_all()
            log.info("run finished: %s", summary)
            return summary
