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


def artifact_filename(kind: str, version: int, ext: str) -> str:
    return f"{kind}_v{version}.{ext}"


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
