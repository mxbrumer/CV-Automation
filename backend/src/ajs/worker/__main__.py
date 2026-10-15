"""Worker entry point: `python -m ajs.worker`. Polls the feeds on a schedule (no ports)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from ajs.db.session import get_engine
from ajs.services.fetch_posting import PostingFetcher
from ajs.services.langflow_client import LangflowClient
from ajs.settings import Settings, get_settings
from ajs.telemetry import setup_telemetry
from ajs.worker.pipeline import LangflowFlowRunner, Pipeline, RunSummary
from ajs.worker.sources.jobindex_rss import JobindexRssSource

log = logging.getLogger("ajs.worker")
LOCK_KEY = 70_707_001  # pg advisory lock: one pipeline run at a time


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


def build_pipeline(session: Session, settings: Settings) -> Pipeline:
    return Pipeline(
        session,
        settings,
        JobindexRssSource(settings.feed_urls, settings.fetch_user_agent),
        PostingFetcher(settings),
        LangflowFlowRunner(LangflowClient(settings)),
    )


def run_once(settings: Settings, generation_only: int | None = None) -> RunSummary | None:
    """One locked pipeline run: analysis (steps 1-10), then generation for approved matches."""
    engine = get_engine()
    with advisory_lock(engine) as acquired:
        if not acquired:
            log.info("another pipeline run holds the lock; skipping")
            return None
        with Session(engine) as session:
            pipeline = build_pipeline(session, settings)
            summary = RunSummary() if generation_only is not None else pipeline.run_analysis()
            generated = pipeline.run_generation(generation_only)
            summary.generated += generated.generated
            summary.errors += generated.errors
            summary.notes += generated.notes
            log.info("run finished: %s", summary)
            return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    setup_telemetry(settings, "ajs-worker", engine=get_engine())
    if not settings.feed_urls:
        log.warning("JOBINDEX_FEEDS is empty: nothing to poll")
    interval = max(settings.feed_poll_interval_min, 1440)  # never below the feed ttl
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_once,
        "interval",
        minutes=interval,
        args=[settings],
        id="poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now().astimezone() + timedelta(seconds=15),  # first run at start
    )
    log.info("worker started; polling every %s min", interval)
    scheduler.start()


if __name__ == "__main__":
    main()
