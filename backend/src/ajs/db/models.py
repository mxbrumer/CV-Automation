"""SQLAlchemy 2.0 models. FastAPI owns this schema (architecture §4, §6)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ajs.db.base import Base


def _enum(cls: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class PostingStatus(enum.StrEnum):
    NEW = "new"
    ANALYZED = "analyzed"
    LOW_MATCH = "low_match"
    AWAITING_MATCH_REVIEW = "awaiting_match_review"
    MATCH_DECLINED = "match_declined"
    MATCHED = "matched"
    GENERATING = "generating"
    GENERATED = "generated"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    DECLINED = "declined"
    DUPLICATE = "duplicate"
    NEEDS_MANUAL_TEXT = "needs_manual_text"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    ERROR = "error"


class Actor(enum.StrEnum):
    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


class ArtifactKind(enum.StrEnum):
    CV = "cv"
    COVER_LETTER = "cover_letter"
    RECRUITER_EMAIL = "recruiter_email"


class ChatRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class DimCompany(Base):
    __tablename__ = "dim_company"

    company_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    name_normalized: Mapped[str] = mapped_column(String(300), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    postings: Mapped[list[FactPosting]] = relationship(back_populates="company")

    __table_args__ = (
        Index(
            "ix_dim_company_name_normalized_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
    )


class FeedItem(Base):
    __tablename__ = "feed_item"

    feed_item_id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="jobindex")
    source_job_id: Mapped[str] = mapped_column(String(100))
    feed_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(Text)
    description_html: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_feed_item_source_job"),)


class FactPosting(Base):
    __tablename__ = "fact_posting"

    posting_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("dim_company.company_id"))
    title: Mapped[str] = mapped_column(Text)
    title_normalized: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), default="jobindex")
    source_job_id: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text)
    posting_text: Mapped[str | None] = mapped_column(Text)
    posting_language: Mapped[str | None] = mapped_column(String(10))
    recruiter_name: Mapped[str | None] = mapped_column(String(200))
    recruiter_email: Mapped[str | None] = mapped_column(String(320))
    recruiter_phone: Mapped[str | None] = mapped_column(String(50))
    job_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    embedding_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    rubric_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    match_rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PostingStatus] = mapped_column(
        _enum(PostingStatus, "posting_status"),
        default=PostingStatus.NEW,
        server_default=PostingStatus.NEW.value,
    )
    match_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_folder: Mapped[str | None] = mapped_column(Text)
    queue_position: Mapped[int | None] = mapped_column(Integer)
    feed_item_id: Mapped[int | None] = mapped_column(ForeignKey("feed_item.feed_item_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[DimCompany] = relationship(back_populates="postings")
    events: Mapped[list[PostingEvent]] = relationship(back_populates="posting")
    artifacts: Mapped[list[ApplicationArtifact]] = relationship(back_populates="posting")

    __table_args__ = (
        Index(
            "uq_fact_posting_source_url",
            "source_url",
            unique=True,
            postgresql_where=text("source_url IS NOT NULL"),
        ),
        Index(
            "uq_fact_posting_source_job",
            "source",
            "source_job_id",
            unique=True,
            postgresql_where=text("source_job_id IS NOT NULL"),
        ),
        Index(
            "ix_fact_posting_title_normalized_trgm",
            "title_normalized",
            postgresql_using="gin",
            postgresql_ops={"title_normalized": "gin_trgm_ops"},
        ),
        Index("ix_fact_posting_status", "status"),
        Index("ix_fact_posting_company_id", "company_id"),
    )


class PostingEvent(Base):
    __tablename__ = "posting_event"

    event_id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("fact_posting.posting_id"))
    from_status: Mapped[PostingStatus | None] = mapped_column(
        _enum(PostingStatus, "posting_status")
    )
    to_status: Mapped[PostingStatus] = mapped_column(_enum(PostingStatus, "posting_status"))
    actor: Mapped[Actor] = mapped_column(_enum(Actor, "event_actor"))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    posting: Mapped[FactPosting] = relationship(back_populates="events")

    __table_args__ = (Index("ix_posting_event_posting_id", "posting_id"),)


class ApplicationArtifact(Base):
    __tablename__ = "application_artifact"

    artifact_id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("fact_posting.posting_id"))
    kind: Mapped[ArtifactKind] = mapped_column(_enum(ArtifactKind, "artifact_kind"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    md_path: Mapped[str] = mapped_column(Text)
    pdf_path: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    posting: Mapped[FactPosting] = relationship(back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("posting_id", "kind", "version", name="uq_application_artifact_version"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"

    message_id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("fact_posting.posting_id"))
    artifact_kind: Mapped[ArtifactKind] = mapped_column(_enum(ArtifactKind, "artifact_kind"))
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole, "chat_role"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_chat_message_posting_id", "posting_id"),)


class WorkflowRun(Base):
    __tablename__ = "workflow_run"

    run_id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int | None] = mapped_column(ForeignKey("fact_posting.posting_id"))
    langflow_flow_id: Mapped[str | None] = mapped_column(String(100))
    langflow_run_id: Mapped[str | None] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(50))  # analysis | generation
    status: Mapped[str] = mapped_column(String(50))  # running | succeeded | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    phoenix_trace_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (Index("ix_workflow_run_posting_id", "posting_id"),)
