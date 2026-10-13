"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-13 18:40:56.539351

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

ENUMS = {
    "posting_status": (
        "new",
        "analyzed",
        "low_match",
        "awaiting_match_review",
        "match_declined",
        "matched",
        "generating",
        "generated",
        "approved",
        "submitted",
        "declined",
        "duplicate",
        "needs_manual_text",
        "unsupported_language",
        "error",
    ),
    "event_actor": ("agent", "user", "system"),
    "artifact_kind": ("cv", "cover_letter", "recruiter_email"),
    "chat_role": ("user", "assistant"),
}

DASHBOARD_COUNTS_SQL = """
CREATE FUNCTION dashboard_counts(threshold numeric)
RETURNS TABLE (reviewed bigint, awaiting_match_review bigint, good_match bigint)
LANGUAGE sql STABLE AS $$
    SELECT
        count(*) FILTER (WHERE status <> 'duplicate'),
        count(*) FILTER (WHERE status = 'awaiting_match_review'),
        count(*) FILTER (WHERE match_score >= threshold)
    FROM fact_posting
$$
"""

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind())
    op.create_table(
        "dim_company",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("name_normalized", sa.String(length=300), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("company_id", name=op.f("pk_dim_company")),
        sa.UniqueConstraint("name_normalized", name=op.f("uq_dim_company_name_normalized")),
    )
    op.create_index(
        "ix_dim_company_name_normalized_trgm",
        "dim_company",
        ["name_normalized"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name_normalized": "gin_trgm_ops"},
    )
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
    op.create_table(
        "fact_posting",
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_job_id", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("posting_text", sa.Text(), nullable=True),
        sa.Column("posting_language", sa.String(length=10), nullable=True),
        sa.Column("recruiter_name", sa.String(length=200), nullable=True),
        sa.Column("recruiter_email", sa.String(length=320), nullable=True),
        sa.Column("recruiter_phone", sa.String(length=50), nullable=True),
        sa.Column("job_brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("rubric_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("match_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("match_rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "new",
                "analyzed",
                "low_match",
                "awaiting_match_review",
                "match_declined",
                "matched",
                "generating",
                "generated",
                "approved",
                "submitted",
                "declined",
                "duplicate",
                "needs_manual_text",
                "unsupported_language",
                "error",
                name="posting_status",
                create_type=False,
            ),
            server_default="new",
            nullable=False,
        ),
        sa.Column("match_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_folder", sa.Text(), nullable=True),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("feed_item_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["dim_company.company_id"],
            name=op.f("fk_fact_posting_company_id_dim_company"),
        ),
        sa.ForeignKeyConstraint(
            ["feed_item_id"],
            ["feed_item.feed_item_id"],
            name=op.f("fk_fact_posting_feed_item_id_feed_item"),
        ),
        sa.PrimaryKeyConstraint("posting_id", name=op.f("pk_fact_posting")),
    )
    op.create_index("ix_fact_posting_company_id", "fact_posting", ["company_id"], unique=False)
    op.create_index("ix_fact_posting_status", "fact_posting", ["status"], unique=False)
    op.create_index(
        "ix_fact_posting_title_normalized_trgm",
        "fact_posting",
        ["title_normalized"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_fact_posting_source_job",
        "fact_posting",
        ["source", "source_job_id"],
        unique=True,
        postgresql_where=sa.text("source_job_id IS NOT NULL"),
    )
    op.create_index(
        "uq_fact_posting_source_url",
        "fact_posting",
        ["source_url"],
        unique=True,
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )
    op.create_table(
        "application_artifact",
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "cv", "cover_letter", "recruiter_email", name="artifact_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("md_path", sa.Text(), nullable=False),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["fact_posting.posting_id"],
            name=op.f("fk_application_artifact_posting_id_fact_posting"),
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_application_artifact")),
        sa.UniqueConstraint(
            "posting_id", "kind", "version", name="uq_application_artifact_version"
        ),
    )
    op.create_table(
        "chat_message",
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column(
            "artifact_kind",
            postgresql.ENUM(
                "cv", "cover_letter", "recruiter_email", name="artifact_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM("user", "assistant", name="chat_role", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["fact_posting.posting_id"],
            name=op.f("fk_chat_message_posting_id_fact_posting"),
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_chat_message")),
    )
    op.create_index("ix_chat_message_posting_id", "chat_message", ["posting_id"], unique=False)
    op.create_table(
        "posting_event",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column(
            "from_status",
            postgresql.ENUM(
                "new",
                "analyzed",
                "low_match",
                "awaiting_match_review",
                "match_declined",
                "matched",
                "generating",
                "generated",
                "approved",
                "submitted",
                "declined",
                "duplicate",
                "needs_manual_text",
                "unsupported_language",
                "error",
                name="posting_status",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(
                "new",
                "analyzed",
                "low_match",
                "awaiting_match_review",
                "match_declined",
                "matched",
                "generating",
                "generated",
                "approved",
                "submitted",
                "declined",
                "duplicate",
                "needs_manual_text",
                "unsupported_language",
                "error",
                name="posting_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "actor",
            postgresql.ENUM("agent", "user", "system", name="event_actor", create_type=False),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["fact_posting.posting_id"],
            name=op.f("fk_posting_event_posting_id_fact_posting"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_posting_event")),
    )
    op.create_index("ix_posting_event_posting_id", "posting_event", ["posting_id"], unique=False)
    op.create_table(
        "workflow_run",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=True),
        sa.Column("langflow_flow_id", sa.String(length=100), nullable=True),
        sa.Column("langflow_run_id", sa.String(length=100), nullable=True),
        sa.Column("phase", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("phoenix_trace_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["fact_posting.posting_id"],
            name=op.f("fk_workflow_run_posting_id_fact_posting"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_workflow_run")),
    )
    op.create_index("ix_workflow_run_posting_id", "workflow_run", ["posting_id"], unique=False)
    op.execute(DASHBOARD_COUNTS_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION dashboard_counts(numeric)")
    op.drop_index("ix_workflow_run_posting_id", table_name="workflow_run")
    op.drop_table("workflow_run")
    op.drop_index("ix_posting_event_posting_id", table_name="posting_event")
    op.drop_table("posting_event")
    op.drop_index("ix_chat_message_posting_id", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_table("application_artifact")
    op.drop_index(
        "uq_fact_posting_source_url",
        table_name="fact_posting",
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )
    op.drop_index(
        "uq_fact_posting_source_job",
        table_name="fact_posting",
        postgresql_where=sa.text("source_job_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_fact_posting_title_normalized_trgm",
        table_name="fact_posting",
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    )
    op.drop_index("ix_fact_posting_status", table_name="fact_posting")
    op.drop_index("ix_fact_posting_company_id", table_name="fact_posting")
    op.drop_table("fact_posting")
    op.drop_table("feed_item")
    op.drop_index(
        "ix_dim_company_name_normalized_trgm",
        table_name="dim_company",
        postgresql_using="gin",
        postgresql_ops={"name_normalized": "gin_trgm_ops"},
    )
    op.drop_table("dim_company")
    for name, values in reversed(ENUMS.items()):
        postgresql.ENUM(*values, name=name).drop(op.get_bind())
