"""Rename stored documents to the `CV_<Company>` scheme and update their paths in the database.

One-off for files written before the scheme existed (`cv_v1.md`, `cover_letter_v3.pdf`, ...).
The latest version of each document gets the clean name in the posting folder; older versions
move to `versions/<name>_v{n}.*`. Safe to rerun: files already at their target are skipped.

Dry run (prints the plan): `uv run python scripts/rename_artifacts.py`
Apply: add `--apply`. Back up first: `scripts/dev.ps1 backup` and a copy of `applications`.
In the stack: `docker exec -i ajs-backend-1 python - --apply < backend/scripts/rename_artifacts.py`.
"""

import argparse
from itertools import groupby

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ajs.db.models import ApplicationArtifact, FactPosting
from ajs.services import blob
from ajs.settings import get_settings


def targets(posting: FactPosting, artifact: ApplicationArtifact, latest: bool) -> dict[str, str]:
    """Wanted relative path for each stored file of `artifact` ("md", and "pdf" if it has one)."""
    folder = posting.artifact_folder
    assert folder is not None
    version = None if latest else artifact.version
    sub = [] if latest else [blob.VERSIONS_DIR]
    wanted = {}
    for ext in ("md", "pdf") if artifact.pdf_path else ("md",):
        name = blob.artifact_filename(artifact.kind.value, posting.company.name, ext, version)
        wanted[ext] = "/".join([folder, *sub, name])
    return wanted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="move the files and update the DB")
    args = parser.parse_args()
    settings = get_settings()
    store = blob.BlobStore(settings)
    moved = missing = 0
    with Session(create_engine(settings.database_url)) as session:
        artifacts = session.scalars(
            select(ApplicationArtifact).order_by(
                ApplicationArtifact.posting_id,
                ApplicationArtifact.kind,
                ApplicationArtifact.version,
            )
        ).all()
        for (posting_id, _), group in groupby(artifacts, key=lambda a: (a.posting_id, a.kind)):
            versions = list(group)
            posting = session.get_one(FactPosting, posting_id)
            for artifact in versions:
                wanted = targets(posting, artifact, latest=artifact is versions[-1])
                for ext, target in wanted.items():
                    current = artifact.md_path if ext == "md" else artifact.pdf_path
                    assert current is not None
                    if current == target:
                        continue
                    if not store.resolve(*current.split("/")).is_file():
                        print(f"missing  {current}")
                        missing += 1
                        continue
                    print(f"{'move' if args.apply else 'would'}     {current} -> {target}")
                    moved += 1
                    if args.apply:
                        new = store.move(current, *target.split("/"))
                        if ext == "md":
                            artifact.md_path = new
                        else:
                            artifact.pdf_path = new
            if args.apply:
                session.commit()  # per document, so files and rows never drift far apart
    verb = "Moved" if args.apply else "Would move"
    print(f"{verb} {moved} files; {missing} missing on disk (left as they are).")


if __name__ == "__main__":
    main()
