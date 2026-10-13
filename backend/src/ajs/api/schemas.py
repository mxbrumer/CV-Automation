"""Request/response models. LangFlow components mirror the tool schemas (see openapi.json)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ajs.db.models import ArtifactKind, PostingStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- tool endpoints --------------------------------------------------------------------------


class FindRequest(BaseModel):
    company: str
    title: str
    source: str = "jobindex"
    source_url: str | None = None
    source_job_id: str | None = None


class FindResponse(BaseModel):
    exists: bool
    posting_id: int | None = None
    reason: str


class CreatePostingRequest(BaseModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = "jobindex"
    source_job_id: str | None = None
    source_url: str | None = None
    posting_text: str | None = None
    feed_item_id: int | None = None


class PostingIdResponse(BaseModel):
    posting_id: int


class AnalysisRequest(BaseModel):
    language: str = Field(min_length=2, max_length=10)
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    recruiter_phone: str | None = None
    job_brief: dict[str, Any]


class MatchRequest(BaseModel):
    embedding_score: float = Field(ge=0, le=100)
    rubric_score: float = Field(ge=0, le=100)
    rationale: str


class MatchResponse(BaseModel):
    posting_id: int
    match_score: float
    status: PostingStatus


class StatusRequest(BaseModel):
    to: PostingStatus
    note: str | None = None


class StatusResponse(BaseModel):
    posting_id: int
    status: PostingStatus


class CvSection(BaseModel):
    id: str
    heading: str
    markdown: str


class TemplateKind(StrEnum):
    COVER_LETTER = "cover_letter"
    RECRUITER_EMAIL = "recruiter_email"


class TemplateResponse(BaseModel):
    kind: TemplateKind
    markdown: str


class FolderResponse(BaseModel):
    path: str
    host_path: str


class ArtifactRequest(BaseModel):
    kind: ArtifactKind
    markdown: str = Field(min_length=1)


class ArtifactBody(BaseModel):
    markdown: str = Field(min_length=1)


# ---- UI endpoints ----------------------------------------------------------------------------


class Stats(BaseModel):
    reviewed: int
    awaiting_match_review: int
    good_match: int


class ArtifactOut(ORMModel):
    artifact_id: int
    kind: ArtifactKind
    version: int
    md_path: str
    pdf_path: str | None
    approved: bool
    created_at: datetime


class ArtifactContent(ArtifactOut):
    markdown: str


class EventOut(ORMModel):
    event_id: int
    from_status: PostingStatus | None
    to_status: PostingStatus
    actor: str
    note: str | None
    at: datetime


class PostingSummary(BaseModel):
    posting_id: int
    company: str
    title: str
    status: PostingStatus
    posting_language: str | None
    match_score: float | None
    queue_position: int | None
    source_url: str | None
    created_at: datetime
    updated_at: datetime


class PostingDetail(PostingSummary):
    posting_text: str | None
    recruiter_name: str | None
    recruiter_email: str | None
    recruiter_phone: str | None
    job_brief: dict[str, Any] | None
    embedding_score: float | None
    rubric_score: float | None
    match_rationale: str | None
    artifact_folder: str | None
    host_folder: str | None
    artifacts: list[ArtifactOut]
    events: list[EventOut]


class PostingPage(BaseModel):
    items: list[PostingSummary]
    total: int
    page: int
    page_size: int


class Decision(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"


class MatchDecisionRequest(BaseModel):
    decision: Decision
    note: str | None = None


class QueueAction(StrEnum):
    SUBMITTED = "submitted"
    DECLINED = "declined"
    SKIP = "skip"


class QueueActionRequest(BaseModel):
    action: QueueAction


class WorkflowPhase(StrEnum):
    ANALYSIS = "analysis"
    GENERATION = "generation"


class WorkflowRunRequest(BaseModel):
    phase: WorkflowPhase
    posting_id: int | None = None
    input_value: str = ""


class WorkflowRunOut(ORMModel):
    run_id: int
    posting_id: int | None
    phase: str
    status: str
    langflow_flow_id: str | None
    error: str | None
