"""Blob storage under DATA_ROOT/applications. Every path is resolved and checked (no traversal)."""

import re
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from ajs.settings import Settings


class UnsafePath(ValueError):
    pass


def slugify(text: str, max_len: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_len].strip("-") or "x"


def folder_name(created: datetime, company: str, title: str, posting_id: int) -> str:
    return f"{created:%Y-%m}_{slugify(company)}_{slugify(title)}_{posting_id}"


VERSIONS_DIR = "versions"
DOC_LABELS = {"cv": "CV"}  # other kinds keep their name: cover_letter, recruiter_email
# NFKD splits å and é into letter + accent, but has no decomposition for these.
TRANSLITERATE = str.maketrans({"æ": "ae", "Æ": "Ae", "ø": "o", "Ø": "O", "ß": "ss"})


def file_token(text: str, max_len: int = 40) -> str:
    """`Danske Commodities` -> `Danske_Commodities`: ASCII, case kept, underscores between words."""
    ascii_text = unicodedata.normalize("NFKD", text.translate(TRANSLITERATE))
    ascii_text = ascii_text.encode("ascii", "ignore").decode()
    token = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")
    return token[:max_len].strip("_") or "x"


def artifact_filename(kind: str, company: str, ext: str, version: int | None = None) -> str:
    """`CV_Danske_Commodities.pdf` for the latest version; with `version`, the name of an older
    one (`CV_Danske_Commodities_v2.pdf`), which is kept in the `versions/` subfolder."""
    stem = f"{DOC_LABELS.get(kind, kind)}_{file_token(company)}"
    return f"{stem}_v{version}.{ext}" if version is not None else f"{stem}.{ext}"


def _bad_segment(part: str) -> bool:
    return (
        not part
        or part in {".", ".."}
        or "/" in part
        or "\\" in part
        or "\0" in part
        or PurePosixPath(part).is_absolute()
        or bool(PureWindowsPath(part).drive)
    )


class BlobStore:
    def __init__(self, settings: Settings) -> None:
        self.root = settings.applications_root
        self._data_root = settings.data_root
        self._host_root = settings.host_data_root

    def resolve(self, *parts: str) -> Path:
        """Join `parts` under the root; reject absolute parts, `..` and symlink escapes."""
        root = self.root.resolve()
        for part in parts:
            if _bad_segment(part):
                raise UnsafePath(f"unsafe path segment: {part!r}")
        path = root.joinpath(*parts).resolve()
        if path != root and root not in path.parents:
            raise UnsafePath("path escapes the applications folder")
        return path

    def make_folder(self, name: str) -> Path:
        path = self.resolve(name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, folder: str, filename: str, content: str) -> Path:
        path = self.resolve(folder, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def write_bytes(self, folder: str, filename: str, content: bytes) -> Path:
        path = self.resolve(folder, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def move(self, relative_path: str, *parts: str) -> str:
        """Move a stored file to `parts` under the root; returns the new relative path. A file that
        is already gone is left alone and its old path returned."""
        source = self.resolve(*relative_path.split("/"))
        if not source.is_file():
            return relative_path
        target = self.resolve(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        return self.relative(target)

    def relative(self, path: Path) -> str:
        """Path relative to the applications root, with forward slashes (stored in the DB)."""
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def read_text(self, relative_path: str) -> str:
        return self.resolve(*relative_path.split("/")).read_text(encoding="utf-8")

    def host_path(self, path: Path) -> str:
        """Map a container path to the Windows path under HOST_DATA_ROOT for display."""
        if not self._host_root:
            return str(path)
        rel = path.resolve().relative_to(self._data_root.resolve())
        return str(PureWindowsPath(self._host_root, *rel.parts))
