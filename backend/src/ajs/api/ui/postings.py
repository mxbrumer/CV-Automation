"""UI endpoints (`/api/v1`) for the React app."""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
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
from ajs.services import pipeline, postings
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
    sort: Literal["score", "recent"] = "score",
) -> schemas.PostingPage:
    stmt = select(FactPosting).join(Company)
    if status:
        stmt = stmt.where(FactPosting.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(FactPosting.title.ilike(like), Company.name.ilike(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = (
        (FactPosting.created_at.desc(), FactPosting.posting_id.desc())
        if sort == "recent"
        else (FactPosting.match_score.desc().nulls_last(), FactPosting.posting_id.desc())
    )
    rows = session.scalars(
        stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return schemas.PostingPage(
        items=[_summary(p) for p in rows], total=total, page=page, page_size=page_size
    )


def _duplicate(reason: schemas.DuplicateReason, posting: FactPosting) -> JSONResponse:
    body = schemas.DuplicateResponse(reason=reason, posting=_summary(posting))
    return JSONResponse(body.model_dump(mode="json"), status_code=409)


@router.post(
    "/postings",
    status_code=201,
    response_model=schemas.PostingSummary,
    responses={409: {"model": schemas.DuplicateResponse, "description": "Duplicate (A5)"}},
)
def add_job(
    body: schemas.CreateJobRequest,
    session: SessionDep,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> schemas.PostingSummary | JSONResponse:
    """Add job form (D3): dedup (A5), store the pasted posting and start its analysis."""
    if body.url is not None:  # the URL is unique across every row, `duplicate` ones included
        same = session.scalars(
            select(FactPosting).where(FactPosting.source_url == body.url)
        ).first()
        if same is not None:
            return _duplicate(schemas.DuplicateReason.SAME_URL, same)
    hit, _ = postings.find_duplicate(
        session,
        settings,
        company=body.company,
        title=body.title,
        source="manual",
        source_url=body.url,
    )
    if hit is not None and not body.force:
        return _duplicate(schemas.DuplicateReason.SIMILAR, hit)
    posting = postings.create_posting(
        session,
        company=body.company,
        title=body.title,
        source="manual",
        source_url=body.url,
        posting_text=body.text,
    )
    session.commit()  # the analysis run must see the new posting
    background.add_task(run_pipeline, settings)
    return _summary(posting)


@router.get("/workflow/last-run")
def last_workflow_run(session: SessionDep) -> schemas.LastRun | None:
    run = session.scalars(select(WorkflowRun).order_by(WorkflowRun.run_id.desc()).limit(1)).first()
    return schemas.LastRun.model_validate(run) if run else None


@router.get("/postings/{posting_id}")
def get_posting(posting_id: int, session: SessionDep, store: BlobDep) -> schemas.PostingDetail:
    return _detail(postings.get_posting(session, posting_id), store)


def _artifact_content(
    session: Session,
    store: BlobStore,
    posting_id: int,
    kind: ArtifactKind,
    version: int | None = None,
) -> schemas.ArtifactContent:
    artifact = (
        postings.latest_artifact(session, posting_id, kind)
        if version is None
        else postings.artifact_version(session, posting_id, kind, version)
    )
    if artifact is None:
        raise HTTPException(404, f"no {kind.value} saved for posting {posting_id}")
    return schemas.ArtifactContent(
        **schemas.ArtifactOut.model_validate(artifact).model_dump(),
        markdown=store.read_text(artifact.md_path),
    )


@router.get("/postings/{posting_id}/artifacts/{kind}")
def get_artifact(
    posting_id: int,
    kind: ArtifactKind,
    session: SessionDep,
    store: BlobDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> schemas.ArtifactContent:
    postings.get_posting(session, posting_id)
    return _artifact_content(session, store, posting_id, kind, version)


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
        background.add_task(run_pipeline, settings)
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
        note = f"queue: {body.action.value}" + (f" - {body.note}" if body.note else "")
        transition(session, posting, target, Actor.USER, note)
        posting.queue_position = None
        if target is PostingStatus.SUBMITTED:
            posting.submitted_at = datetime.now(UTC)
    return _summary(posting)


@router.get("/files/{posting_id}/{filename:path}")
def get_file(posting_id: int, filename: str, session: SessionDep, store: BlobDep) -> FileResponse:
    """`filename` is relative to the posting's folder, e.g. `versions/CV_Acme_v1.pdf`."""
    posting = postings.get_posting(session, posting_id)
    if posting.artifact_folder is None:
        raise HTTPException(404, "posting has no folder yet")
    path = store.resolve(posting.artifact_folder, *filename.split("/"))
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path)


def run_pipeline(settings: Settings) -> None:
    """Background job: one locked run of everything pending. A run started while another holds
    the lock is skipped; the running one picks up what arrived before it ends."""
    if settings.env == "test":  # browser e2e: no LangFlow, drafts are seeded
        return
    pipeline.run_once(settings)


@router.post("/workflow/process-pending", status_code=202)
def process_pending(background: BackgroundTasks, settings: SettingsDep) -> dict[str, str]:
    """Recovery after a lost background run: analysis for `new`, generation for `matched`."""
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
