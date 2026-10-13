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
            "feed_item",
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
