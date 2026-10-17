"""Migration smoke test. Needs DATABASE_URL pointing at an empty scratch database."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from ajs.db.base import Base
from ajs.db.models import PostingStatus

BACKEND = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL not set")


@pytest.fixture
def alembic_cfg() -> Iterator[Config]:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.downgrade(cfg, "base")
    yield cfg
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # later tests share the session-scoped schema (conftest)


def test_upgrade_matches_models_and_downgrades(alembic_cfg: Config) -> None:
    assert DATABASE_URL is not None
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == []
        tables = set(
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
        assert {
            "dim_company",
            "fact_posting",
            "posting_event",
            "application_artifact",
            "chat_message",
            "workflow_run",
        } <= tables
        labels = list(
            conn.execute(text("SELECT unnest(enum_range(NULL::posting_status))::text")).scalars()
        )
        assert labels == [s.value for s in PostingStatus]
        assert conn.execute(text("SELECT * FROM dashboard_counts(55)")).one() == (0, 0, 0)

    command.downgrade(alembic_cfg, "base")
    with engine.connect() as conn:
        left = set(
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
        assert left <= {"alembic_version"}
        assert (
            conn.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'posting_status'")
            ).scalar()
            == 0
        )
    engine.dispose()


def test_0002_deletes_stranded_feed_postings_only(alembic_cfg: Config) -> None:
    """Plan 15: jobindex postings without text go (with every child row); the rest stays."""
    assert DATABASE_URL is not None
    command.upgrade(alembic_cfg, "0001")
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        company = conn.execute(
            text(
                "INSERT INTO dim_company (name, name_normalized) "
                "VALUES ('Acme', 'acme') RETURNING company_id"
            )
        ).scalar_one()
        feed = conn.execute(
            text(
                "INSERT INTO feed_item (source, source_job_id, feed_url, title, link) "
                "VALUES ('jobindex', 'h1', 'f', 't', 'l') RETURNING feed_item_id"
            )
        ).scalar_one()

        def posting(title: str, source: str, status: str, posting_text: str | None) -> int:
            return int(
                conn.execute(
                    text(
                        "INSERT INTO fact_posting (company_id, title, title_normalized, source, "
                        "status, posting_text, feed_item_id) VALUES (:c, :t, :t, :s, "
                        "CAST(:st AS posting_status), :pt, :f) RETURNING posting_id"
                    ),
                    {
                        "c": company,
                        "t": title,
                        "s": source,
                        "st": status,
                        "pt": posting_text,
                        "f": feed,
                    },
                ).scalar_one()
            )

        stranded = posting("needs text", "jobindex", "needs_manual_text", None)
        no_text = posting("new without text", "jobindex", "new", None)
        kept = [
            posting("new with text", "jobindex", "new", "full text"),
            posting("scored", "jobindex", "low_match", "full text"),
            posting("manual", "manual", "needs_manual_text", None),
        ]
        for pid in [stranded, no_text, *kept]:
            conn.execute(
                text(
                    "INSERT INTO posting_event (posting_id, to_status, actor) "
                    "VALUES (:p, 'new', 'system')"
                ),
                {"p": pid},
            )
            conn.execute(
                text(
                    "INSERT INTO workflow_run (posting_id, phase, status) "
                    "VALUES (:p, 'analysis', 'failed')"
                ),
                {"p": pid},
            )
        conn.execute(
            text(
                "INSERT INTO chat_message (posting_id, artifact_kind, role, content) "
                "VALUES (:p, 'cv', 'user', 'x')"
            ),
            {"p": stranded},
        )
        conn.execute(
            text(
                "INSERT INTO application_artifact (posting_id, kind, version, md_path) "
                "VALUES (:p, 'cv', 1, 'x/cv_v1.md')"
            ),
            {"p": stranded},
        )

    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        left = set(conn.execute(text("SELECT posting_id FROM fact_posting")).scalars())
        assert left == set(kept)
        for table in ("posting_event", "workflow_run", "chat_message", "application_artifact"):
            owners = set(conn.execute(text(f"SELECT posting_id FROM {table}")).scalars())
            assert owners <= set(kept), table
        assert set(conn.execute(text("SELECT posting_id FROM posting_event")).scalars()) == set(
            kept
        )
        assert conn.execute(text("SELECT to_regclass('feed_item')")).scalar() is None
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'fact_posting'"
                )
            ).scalars()
        )
        assert "feed_item_id" not in columns

    command.downgrade(alembic_cfg, "0001")  # recreates the empty table and column, not the rows
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM feed_item")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM fact_posting")).scalar() == len(kept)
    engine.dispose()
