"""UI endpoints (`/api/v1`) for the React app."""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ajs.api import schemas
from ajs.api.deps import BlobDep, LangflowDep, SessionDep, SettingsDep
from ajs.db.models import (
    Actor,
    ArtifactKind,
    FactPosting,
    PostingStatus,
    WorkflowRun,
)
from ajs.db.models import DimCompany as Company
from ajs.domain.status import transition
from ajs.services import postings
from ajs.services.blob import BlobStore
from ajs.services.langflow_client import LangflowError
from ajs.settings import Settings

router = APIRouter(tags=["ui"])


def _summary(p: FactPosting) -> schemas.PostingSummary:
    return schemas.PostingSummary(
        posting_id=p.posting_id,
        company=p.company.name,
        title=p.title,
        status=p.status,
        posting_language=p.posting_language,
        match_score=float(p.match_score) if p.match_score is not None else None,
        queue_position=p.queue_position,
        source_url=p.source_url,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _detail(p: FactPosting, store: BlobStore) -> schemas.PostingDetail:
    folder = store.resolve(p.artifact_folder) if p.artifact_folder else None
    return schemas.PostingDetail(
        **_summary(p).model_dump(),
        posting_text=p.posting_text,
        recruiter_name=p.recruiter_name,
        recruiter_email=p.recruiter_email,
        recruiter_phone=p.recruiter_phone,
        job_brief=p.job_brief,
        embedding_score=float(p.embedding_score) if p.embedding_score is not None else None,
        rubric_score=float(p.rubric_score) if p.rubric_score is not None else None,
        match_rationale=p.match_rationale,
        artifact_folder=p.artifact_folder,
        host_folder=store.host_path(folder) if folder else None,
        artifacts=[
            schemas.ArtifactOut.model_validate(a)
            for a in sorted(p.artifacts, key=lambda a: (a.kind.value, a.version))
        ],
        events=[
            schemas.EventOut.model_validate(e) for e in sorted(p.events, key=lambda e: e.event_id)
        ],
    )


@router.get("/stats")
def stats(session: SessionDep, settings: SettingsDep) -> schemas.Stats:
    row = session.execute(
        text("SELECT reviewed, awaiting_match_review, good_match FROM dashboard_counts(:t)"),
        {"t": settings.match_threshold},
    ).one()
    return schemas.Stats(reviewed=row[0], awaiting_match_review=row[1], good_match=row[2])


@router.get("/postings")
def list_postings(
    session: SessionDep,
    status: PostingStatus | None = None,
    q: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> schemas.PostingPage:
    stmt = select(FactPosting).join(Company)
    if status:
        stmt = stmt.where(FactPosting.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(FactPosting.title.ilike(like), Company.name.ilike(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(FactPosting.match_score.desc().nulls_last(), FactPosting.posting_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return schemas.PostingPage(
        items=[_summary(p) for p in rows], total=total, page=page, page_size=page_size
    )


@router.get("/postings/{posting_id}")
def get_posting(posting_id: int, session: SessionDep, store: BlobDep) -> schemas.PostingDetail:
    return _detail(postings.get_posting(session, posting_id), store)


def _artifact_content(
    session: Session, store: BlobStore, posting_id: int, kind: ArtifactKind
) -> schemas.ArtifactContent:
    artifact = postings.latest_artifact(session, posting_id, kind)
    if artifact is None:
        raise HTTPException(404, f"no {kind.value} saved for posting {posting_id}")
    return schemas.ArtifactContent(
        **schemas.ArtifactOut.model_validate(artifact).model_dump(),
        markdown=store.read_text(artifact.md_path),
    )


@router.get("/postings/{posting_id}/artifacts/{kind}")
def get_artifact(
    posting_id: int, kind: ArtifactKind, session: SessionDep, store: BlobDep
) -> schemas.ArtifactContent:
    postings.get_posting(session, posting_id)
    return _artifact_content(session, store, posting_id, kind)


@router.put("/postings/{posting_id}/artifacts/{kind}")
def edit_artifact(
    posting_id: int,
    kind: ArtifactKind,
    body: schemas.ArtifactBody,
    session: SessionDep,
    store: BlobDep,
) -> schemas.ArtifactContent:
    """A manual edit is saved as a new version."""
    posting = postings.get_posting(session, posting_id)
    postings.save_artifact(session, store, posting, kind, body.markdown)
    return _artifact_content(session, store, posting_id, kind)


@router.post("/postings/{posting_id}/match-decision")  # gate 1 (D9)
def match_decision(
    posting_id: int,
    body: schemas.MatchDecisionRequest,
    session: SessionDep,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> schemas.StatusResponse:
    posting = postings.get_posting(session, posting_id)
    target = (
        PostingStatus.MATCHED
        if body.decision is schemas.Decision.APPROVE
        else PostingStatus.MATCH_DECLINED
    )
    transition(session, posting, target, Actor.USER, body.note)
    posting.match_reviewed_at = datetime.now(UTC)
    if target is PostingStatus.MATCHED:
        session.commit()  # the generation run must see the new status
        background.add_task(run_pipeline, settings, posting_id)  # no-op until plan 09's flow
    return schemas.StatusResponse(posting_id=posting_id, status=posting.status)


@router.post("/postings/{posting_id}/approve")  # gate 2 (D9)
def approve(posting_id: int, session: SessionDep) -> schemas.PostingSummary:
    posting = postings.get_posting(session, posting_id)
    transition(session, posting, PostingStatus.APPROVED, Actor.USER, "drafts approved")
    posting.queue_position = postings.next_queue_position(session)
    return _summary(posting)


def _queue_head(session: Session) -> FactPosting | None:
    return session.scalars(
        select(FactPosting)
        .where(FactPosting.status == PostingStatus.APPROVED)
        .order_by(FactPosting.queue_position, FactPosting.posting_id)
        .limit(1)
    ).first()


@router.get("/queue/next")
def queue_next(session: SessionDep) -> schemas.PostingSummary | None:
    head = _queue_head(session)
    return _summary(head) if head else None


@router.post("/queue/{posting_id}/action")
def queue_action(
    posting_id: int, body: schemas.QueueActionRequest, session: SessionDep
) -> schemas.PostingSummary:
    posting = postings.get_posting(session, posting_id)
    if posting.status is not PostingStatus.APPROVED:
        raise HTTPException(409, f"posting is '{posting.status.value}', not in the queue")
    if body.action is schemas.QueueAction.SKIP:  # no status change: move to the end
        posting.queue_position = postings.next_queue_position(session)
    else:
        target = (
            PostingStatus.SUBMITTED
            if body.action is schemas.QueueAction.SUBMITTED
            else PostingStatus.DECLINED
        )
        transition(session, posting, target, Actor.USER, f"queue: {body.action.value}")
        posting.queue_position = None
        if target is PostingStatus.SUBMITTED:
            posting.submitted_at = datetime.now(UTC)
    return _summary(posting)


@router.get("/files/{posting_id}/{filename}")
def get_file(posting_id: int, filename: str, session: SessionDep, store: BlobDep) -> FileResponse:
    posting = postings.get_posting(session, posting_id)
    if posting.artifact_folder is None:
        raise HTTPException(404, "posting has no folder yet")
    path = store.resolve(posting.artifact_folder, filename)
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path)


def run_pipeline(settings: Settings, generation_only: int | None = None) -> None:
    """Background job: the same locked run the worker does (a second run is skipped)."""
    from ajs.worker.__main__ import run_once

    run_once(settings, generation_only)


@router.post("/workflow/poll", status_code=202)  # manual trigger of the worker's job
def poll_now(background: BackgroundTasks, settings: SettingsDep) -> dict[str, str]:
    background.add_task(run_pipeline, settings)
    return {"status": "queued"}


@router.post("/workflow/run")
def run_workflow(
    body: schemas.WorkflowRunRequest, session: SessionDep, langflow: LangflowDep
) -> schemas.WorkflowRunOut:
    if body.posting_id is not None:
        postings.get_posting(session, body.posting_id)
    try:
        flow_id = langflow.flow_id(body.phase.value)
    except LangflowError as exc:
        raise HTTPException(503, str(exc)) from exc
    run = WorkflowRun(
        posting_id=body.posting_id,
        langflow_flow_id=flow_id,
        phase=body.phase.value,
        status="running",
    )
    session.add(run)
    session.commit()  # keep the record even if the flow call fails
    input_value = body.input_value or (
        json.dumps({"posting_id": body.posting_id}) if body.posting_id else ""
    )
    try:
        ref = langflow.run_flow(flow_id, input_value)
        run.status = "succeeded"
        run.langflow_run_id, run.phoenix_trace_id = ref.session_id, ref.trace_id
    except LangflowError as exc:
        run.status, run.error = "failed", str(exc)
    run.finished_at = datetime.now(UTC)
    return schemas.WorkflowRunOut.model_validate(run)
