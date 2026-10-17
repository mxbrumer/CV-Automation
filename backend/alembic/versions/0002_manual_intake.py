"""manual intake (plan 15): drop the feed tables and the postings the feed left stranded

Deletes every `jobindex` posting that never got text (`needs_manual_text`, or `new` without
`posting_text`) together with its chat messages, artifacts, workflow runs and events, then drops
`fact_posting.feed_item_id` and `feed_item`. Blob files are never touched; a folder set on a
deleted posting is only logged.

Downgrade recreates the empty `feed_item` table and the column. The deleted rows are **not**
restored.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 12:00:00

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

STRANDED = """
    SELECT posting_id, artifact_folder FROM fact_posting
    WHERE source = 'jobindex'
      AND (status = 'needs_manual_text' OR (status = 'new' AND posting_text IS NULL))
"""
CHILD_TABLES = ("chat_message", "application_artifact", "workflow_run", "posting_event")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(STRANDED)).all()
    ids = [r.posting_id for r in rows]
    for r in rows:
        if r.artifact_folder:
            log.warning(
                "posting %s had folder %s; files left alone", r.posting_id, r.artifact_folder
            )
    if ids:
        for table in CHILD_TABLES:
            bind.execute(sa.text(f"DELETE FROM {table} WHERE posting_id = ANY(:ids)"), {"ids": ids})
        bind.execute(sa.text("DELETE FROM fact_posting WHERE posting_id = ANY(:ids)"), {"ids": ids})
    log.info("deleted %d stranded feed postings", len(ids))

    op.drop_constraint("fk_fact_posting_feed_item_id_feed_item", "fact_posting", type_="foreignkey")
    op.drop_column("fact_posting", "feed_item_id")
    op.drop_table("feed_item")


def downgrade() -> None:
    op.create_table(
        "feed_item",
        sa.Column("feed_item_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_job_id", sa.String(length=100), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("feed_item_id", name=op.f("pk_feed_item")),
        sa.UniqueConstraint("source", "source_job_id", name="uq_feed_item_source_job"),
    )
    op.add_column("fact_posting", sa.Column("feed_item_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_fact_posting_feed_item_id_feed_item",
        "fact_posting",
        "feed_item",
        ["feed_item_id"],
        ["feed_item_id"],
    )
