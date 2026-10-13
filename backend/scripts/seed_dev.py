"""Seed fake companies and postings, one per status, for frontend development.

Run after `alembic upgrade head`: `uv run python scripts/seed_dev.py`.
Every company is named "Fake ... " so `--reset` can remove exactly the seeded rows.
No real data is used.
"""

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from ajs.db.models import (
    Actor,
    ApplicationArtifact,
    ArtifactKind,
    ChatMessage,
    ChatRole,
    DimCompany,
    FactPosting,
    PostingEvent,
    PostingStatus,
)
from ajs.domain.normalize import normalize_company, normalize_title
from ajs.settings import get_settings

S = PostingStatus

# (status, title, language, match_score) per seeded posting
ROWS: list[tuple[PostingStatus, str, str, float | None]] = [
    (S.NEW, "Data Engineer", "en", None),
    (S.ANALYZED, "Analytics Engineer", "en", None),
    (S.LOW_MATCH, "Marketing Coordinator", "da", 31.0),
    (S.AWAITING_MATCH_REVIEW, "Senior Data Scientist", "da", 78.5),
    (S.AWAITING_MATCH_REVIEW, "BI Developer", "en", 62.0),
    (S.MATCH_DECLINED, "Data Analyst", "da", 58.0),
    (S.MATCHED, "ML Engineer", "en", 81.0),
    (S.GENERATING, "Data Platform Engineer", "en", 74.0),
    (S.GENERATED, "Machine Learning Scientist", "en", 83.0),
    (S.GENERATED, "Head of Analytics", "da", 69.0),
    (S.APPROVED, "Python Developer", "en", 77.0),
    (S.APPROVED, "Forecasting Specialist", "en", 72.0),
    (S.SUBMITTED, "Data Scientist", "en", 85.0),
    (S.DECLINED, "Backend Engineer", "en", 66.0),
    (S.DUPLICATE, "Data Scientist", "en", 85.0),
    (S.NEEDS_MANUAL_TEXT, "Quantitative Analyst", "en", None),
    (S.UNSUPPORTED_LANGUAGE, "Dateningenieur", "de", None),
    (S.ERROR, "Research Engineer", "en", None),
]

FOLDER_STATUSES = {S.GENERATING, S.GENERATED, S.APPROVED, S.SUBMITTED, S.DECLINED}
ARTIFACT_STATUSES = {S.GENERATED, S.APPROVED, S.SUBMITTED, S.DECLINED}


def seed(session: Session) -> int:
    now = datetime.now(UTC)
    queue = 0
    for i, (status, title, language, score) in enumerate(ROWS, start=1):
        name = f"Fake Company {i:02d} A/S"
        company = DimCompany(name=name, name_normalized=normalize_company(name), country="Denmark")
        session.add(company)
        session.flush()
        job_id = f"fake{i:04d}"
        posting = FactPosting(
            company_id=company.company_id,
            title=title,
            title_normalized=normalize_title(title),
            source="jobindex",
            source_job_id=job_id,
            source_url=f"https://www.jobindex.dk/vis-job/{job_id}",
            posting_text=f"Fake posting text for {title}. Python, SQL and statistics required.",
            posting_language=language,
            recruiter_name="Jane Doe" if i % 3 == 0 else None,
            recruiter_email="jane.doe@example.com" if i % 3 == 0 else None,
            job_brief={
                "keywords": ["python", "sql"],
                "location": "Aarhus",
                "relocation_ok": True,
                "required_languages": ["en"] if language != "da" else ["da", "en"],
                "danish_required": language == "da",
                "company_values": ["curiosity", "trust"],
            }
            if score is not None
            else None,
            match_score=score,
            embedding_score=None if score is None else round(score - 5, 2),
            rubric_score=None if score is None else round(score + 3, 2),
            match_rationale=None if score is None else "Fake rationale for dev data.",
            status=status,
            artifact_folder=f"2026-10_fake-company-{i:02d}_{i}"
            if status in FOLDER_STATUSES
            else None,
            created_at=now - timedelta(days=len(ROWS) - i),
        )
        if status is S.APPROVED:
            queue += 1
            posting.queue_position = queue
        if status is S.SUBMITTED:
            posting.submitted_at = now
        session.add(posting)
        session.flush()
        session.add(
            PostingEvent(
                posting_id=posting.posting_id,
                from_status=None,
                to_status=status,
                actor=Actor.SYSTEM,
                note="seed",
            )
        )
        if status in ARTIFACT_STATUSES:
            for kind in ArtifactKind:
                session.add(
                    ApplicationArtifact(
                        posting_id=posting.posting_id,
                        kind=kind,
                        version=1,
                        md_path=f"{posting.artifact_folder}/{kind.value}.md",
                        pdf_path=None
                        if kind is ArtifactKind.RECRUITER_EMAIL
                        else f"{posting.artifact_folder}/{kind.value}.pdf",
                        approved=status in {S.APPROVED, S.SUBMITTED},
                    )
                )
            session.add(
                ChatMessage(
                    posting_id=posting.posting_id,
                    artifact_kind=ArtifactKind.COVER_LETTER,
                    role=ChatRole.USER,
                    content="Make the opening shorter.",
                )
            )
    return len(ROWS)


def reset(session: Session) -> None:
    ids = select(DimCompany.company_id).where(DimCompany.name.like("Fake Company %"))
    posting_ids = select(FactPosting.posting_id).where(FactPosting.company_id.in_(ids))
    session.execute(delete(ChatMessage).where(ChatMessage.posting_id.in_(posting_ids)))
    session.execute(
        delete(ApplicationArtifact).where(ApplicationArtifact.posting_id.in_(posting_ids))
    )
    session.execute(delete(PostingEvent).where(PostingEvent.posting_id.in_(posting_ids)))
    session.execute(delete(FactPosting).where(FactPosting.company_id.in_(ids)))
    session.execute(delete(DimCompany).where(DimCompany.name.like("Fake Company %")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="remove seeded rows first")
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    with Session(engine) as session, session.begin():
        if args.reset:
            reset(session)
        elif session.scalar(
            select(DimCompany.company_id).where(DimCompany.name.like("Fake Company %")).limit(1)
        ):
            raise SystemExit("Seed data already present; rerun with --reset.")
        count = seed(session)
    print(f"Seeded {count} fake postings.")


if __name__ == "__main__":
    main()
