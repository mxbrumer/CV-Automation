"""Posting persistence shared by the tool and UI endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ajs.db.models import (
    Actor,
    ApplicationArtifact,
    ArtifactKind,
    DimCompany,
    FactPosting,
    PostingEvent,
    PostingStatus,
)
from ajs.domain.normalize import normalize_company, normalize_title
from ajs.services import blob, render
from ajs.settings import Settings


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def get_posting(session: Session, posting_id: int) -> FactPosting:
    posting = session.get(FactPosting, posting_id)
    if posting is None:
        raise NotFound(f"posting {posting_id} not found")
    return posting


def find_duplicate(
    session: Session,
    settings: Settings,
    *,
    company: str,
    title: str,
    source: str = "manual",
    source_url: str | None = None,
    source_job_id: str | None = None,
) -> tuple[FactPosting | None, str]:
    """A5: same (source, job id) OR same URL OR fuzzy company and title within the window.

    Manual postings have no job id; old `jobindex` rows still match on it.
    """
    live = FactPosting.status != PostingStatus.DUPLICATE
    if source_job_id:
        hit = session.scalars(
            select(FactPosting).where(
                FactPosting.source == source, FactPosting.source_job_id == source_job_id, live
            )
        ).first()
        if hit:
            return hit, "same source job id"
    if source_url:
        hit = session.scalars(
            select(FactPosting).where(FactPosting.source_url == source_url, live)
        ).first()
        if hit:
            return hit, "same source url"

    company_n, title_n = normalize_company(company), normalize_title(title)
    since = datetime.now(UTC) - timedelta(days=settings.dedup_window_days)
    threshold = settings.dedup_similarity
    row = (
        session.execute(
            select(FactPosting)
            .join(DimCompany)
            .where(
                live,
                FactPosting.created_at >= since,
                func.similarity(DimCompany.name_normalized, company_n) >= threshold,
                func.similarity(FactPosting.title_normalized, title_n) >= threshold,
            )
            .order_by(
                (
                    func.similarity(DimCompany.name_normalized, company_n)
                    + func.similarity(FactPosting.title_normalized, title_n)
                ).desc()
            )
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row:
        return row, f"similar company and title (>= {threshold})"
    return None, "no match"


def upsert_company(session: Session, name: str) -> DimCompany:
    normalized = normalize_company(name) or name.casefold().strip()
    company = session.scalars(
        select(DimCompany).where(DimCompany.name_normalized == normalized)
    ).first()
    if company is None:
        company = DimCompany(name=name.strip(), name_normalized=normalized)
        session.add(company)
        session.flush()
    return company


def create_posting(session: Session, *, company: str, title: str, **fields: Any) -> FactPosting:
    company_row = upsert_company(session, company)
    posting = FactPosting(
        company_id=company_row.company_id,
        title=title.strip(),
        title_normalized=normalize_title(title),
        status=PostingStatus.NEW,
        **fields,
    )
    session.add(posting)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("a posting with this source job id or url already exists") from exc
    session.add(
        PostingEvent(
            posting_id=posting.posting_id,
            from_status=None,
            to_status=PostingStatus.NEW,
            actor=Actor.AGENT,
            note="created",
        )
    )
    session.flush()
    return posting


def ensure_folder(session: Session, store: blob.BlobStore, posting: FactPosting) -> str:
    """Create the posting's folder once; returns the name relative to the applications root."""
    if posting.artifact_folder is None:
        name = blob.folder_name(
            posting.created_at, posting.company.name, posting.title, posting.posting_id
        )
        store.make_folder(name)
        posting.artifact_folder = name
        session.flush()
    return posting.artifact_folder


def latest_artifact(
    session: Session, posting_id: int, kind: ArtifactKind
) -> ApplicationArtifact | None:
    return session.scalars(
        select(ApplicationArtifact)
        .where(ApplicationArtifact.posting_id == posting_id, ApplicationArtifact.kind == kind)
        .order_by(ApplicationArtifact.version.desc())
        .limit(1)
    ).first()


def artifact_version(
    session: Session, posting_id: int, kind: ArtifactKind, version: int
) -> ApplicationArtifact | None:
    return session.scalars(
        select(ApplicationArtifact).where(
            ApplicationArtifact.posting_id == posting_id,
            ApplicationArtifact.kind == kind,
            ApplicationArtifact.version == version,
        )
    ).first()


def save_artifact(
    session: Session, store: blob.BlobStore, posting: FactPosting, kind: ArtifactKind, markdown: str
) -> ApplicationArtifact:
    """Write a new version: `<kind>_v{n}.md`, plus a PDF when the renderer is available."""
    folder = ensure_folder(session, store, posting)
    previous = latest_artifact(session, posting.posting_id, kind)
    version = previous.version + 1 if previous else 1
    md_path = store.write_text(folder, blob.artifact_filename(kind.value, version, "md"), markdown)
    pdf_rel: str | None = None
    if kind is not ArtifactKind.RECRUITER_EMAIL:  # the email is pasted as rich text, no PDF
        try:
            pdf = render.markdown_to_pdf(markdown, render.stylesheet_for(kind.value))
        except OSError:
            pass  # WeasyPrint's system libraries are missing (host runs); the .md is still saved
        else:
            pdf_rel = store.relative(
                store.write_bytes(folder, blob.artifact_filename(kind.value, version, "pdf"), pdf)
            )
    artifact = ApplicationArtifact(
        posting_id=posting.posting_id,
        kind=kind,
        version=version,
        md_path=store.relative(md_path),
        pdf_path=pdf_rel,
    )
    session.add(artifact)
    session.flush()
    return artifact


def next_queue_position(session: Session) -> int:
    current = session.scalar(
        select(func.max(FactPosting.queue_position)).where(
            FactPosting.status == PostingStatus.APPROVED
        )
    )
    return (current or 0) + 1
