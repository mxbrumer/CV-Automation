"""Tool endpoints called by LangFlow (`/api/v1/tools`). Brief step numbers in comments."""

import re

from fastapi import APIRouter, HTTPException

from ajs.api import schemas
from ajs.api.deps import BlobDep, SessionDep, SettingsDep
from ajs.db.models import Actor, PostingStatus
from ajs.domain import scoring
from ajs.domain.status import USER_ONLY, transition
from ajs.services import postings

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/postings/find")  # steps 3-4
def find_posting(
    body: schemas.FindRequest, session: SessionDep, settings: SettingsDep
) -> schemas.FindResponse:
    hit, reason = postings.find_duplicate(
        session,
        settings,
        company=body.company,
        title=body.title,
        source=body.source,
        source_url=body.source_url,
        source_job_id=body.source_job_id,
    )
    return schemas.FindResponse(
        exists=hit is not None, posting_id=hit.posting_id if hit else None, reason=reason
    )


@router.post("/postings", status_code=201)  # step 5
def create_posting(
    body: schemas.CreatePostingRequest, session: SessionDep
) -> schemas.PostingIdResponse:
    posting = postings.create_posting(
        session,
        company=body.company,
        title=body.title,
        source=body.source,
        source_job_id=body.source_job_id,
        source_url=body.source_url,
        posting_text=body.posting_text,
    )
    return schemas.PostingIdResponse(posting_id=posting.posting_id)


@router.patch("/postings/{posting_id}/analysis")  # steps 6-8
def save_analysis(
    posting_id: int, body: schemas.AnalysisRequest, session: SessionDep
) -> schemas.StatusResponse:
    posting = postings.get_posting(session, posting_id)
    transition(session, posting, PostingStatus.ANALYZED, Actor.AGENT, "analysis saved")
    posting.posting_language = body.language
    posting.recruiter_name = body.recruiter_name
    posting.recruiter_email = body.recruiter_email
    posting.recruiter_phone = body.recruiter_phone
    posting.job_brief = body.job_brief
    return schemas.StatusResponse(posting_id=posting_id, status=posting.status)


@router.patch("/postings/{posting_id}/match")  # steps 9-10
def save_match(
    posting_id: int, body: schemas.MatchRequest, session: SessionDep, settings: SettingsDep
) -> schemas.MatchResponse:
    posting = postings.get_posting(session, posting_id)
    score = scoring.match_score(
        body.embedding_score,
        body.rubric_score,
        settings.match_weight_embedding,
        settings.match_weight_rubric,
    )
    target = scoring.status_for_score(score, settings.match_threshold)
    transition(session, posting, target, Actor.AGENT, f"match score {score}")
    posting.embedding_score = body.embedding_score
    posting.rubric_score = body.rubric_score
    posting.match_score = score
    posting.match_rationale = body.rationale
    return schemas.MatchResponse(posting_id=posting_id, match_score=score, status=posting.status)


@router.post("/postings/{posting_id}/status")  # error and side statuses, generation progress
def set_status(
    posting_id: int, body: schemas.StatusRequest, session: SessionDep
) -> schemas.StatusResponse:
    if body.to in USER_ONLY:
        raise HTTPException(403, f"'{body.to.value}' is a user decision, not a tool action")
    posting = postings.get_posting(session, posting_id)
    transition(session, posting, body.to, Actor.AGENT, body.note)
    return schemas.StatusResponse(posting_id=posting_id, status=posting.status)


@router.post("/postings/{posting_id}/folder")  # step 11
def create_folder(posting_id: int, session: SessionDep, store: BlobDep) -> schemas.FolderResponse:
    posting = postings.get_posting(session, posting_id)
    folder = postings.ensure_folder(session, store, posting)
    return schemas.FolderResponse(path=folder, host_path=store.host_path(store.resolve(folder)))


@router.post("/postings/{posting_id}/artifacts", status_code=201)  # steps 12-15
def add_artifact(
    posting_id: int, body: schemas.ArtifactRequest, session: SessionDep, store: BlobDep
) -> schemas.ArtifactOut:
    posting = postings.get_posting(session, posting_id)
    artifact = postings.save_artifact(session, store, posting, body.kind, body.markdown)
    return schemas.ArtifactOut.model_validate(artifact)


def _split_cv(markdown: str) -> list[schemas.CvSection]:
    sections: list[schemas.CvSection] = []
    used: set[str] = set()
    heading = ""
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if not text and not heading:
            return
        base = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "preamble"
        section_id, n = base, 2
        while section_id in used:
            section_id, n = f"{base}-{n}", n + 1
        used.add(section_id)
        sections.append(schemas.CvSection(id=section_id, heading=heading, markdown=text))

    for line in markdown.splitlines():
        if line.startswith("## "):
            flush()
            heading, lines = line[3:].strip(), [line]
        else:
            lines.append(line)
    flush()
    return sections


@router.get("/profile/cv-sections")  # steps 9, 12
def cv_sections(settings: SettingsDep) -> list[schemas.CvSection]:
    path = settings.profile_root / "cv.md"
    if not path.is_file():
        raise HTTPException(404, "cv.md not found in DATA_ROOT/profile")
    return _split_cv(path.read_text(encoding="utf-8"))


@router.get("/profile/templates/{kind}")  # steps 13-14
def template(kind: schemas.TemplateKind, settings: SettingsDep) -> schemas.TemplateResponse:
    path = settings.profile_root / f"{kind.value}_template.md"
    if not path.is_file():
        raise HTTPException(404, f"{path.name} not found in DATA_ROOT/profile")
    return schemas.TemplateResponse(kind=kind, markdown=path.read_text(encoding="utf-8"))
