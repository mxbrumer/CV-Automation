"""Normalisation for company and title dedup (A5)."""

import re
import unicodedata

_LEGAL_SUFFIXES = (
    "a/s",
    "aps",
    "i/s",
    "k/s",
    "p/s",
    "ivs",
    "amba",
    "gmbh",
    "ag",
    "ab",
    "as",
    "oy",
    "ltd",
    "limited",
    "llc",
    "inc",
    "plc",
    "corp",
    "co",
)
_SUFFIX_RE = re.compile(
    r"(?:[\s,.]+(?:" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\.?)+$"
)
_PUNCT_RE = re.compile(r"[^\w\s/&+#.-]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def _base(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_company(name: str) -> str:
    """Lowercase, collapse whitespace and strip legal suffixes such as A/S, ApS, Ltd."""
    text = _base(name)
    text = _SUFFIX_RE.sub("", text).strip(" ,.")
    return text


def normalize_title(title: str) -> str:
    """Lowercase and collapse whitespace; drops gender markers like (m/f/d) or (m/k)."""
    text = re.sub(r"\((?:[mfdwkx]/?)+\)", " ", title.casefold())
    return _base(text)
