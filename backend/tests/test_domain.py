from pathlib import Path

import pytest

from ajs.db.models import PostingStatus as S
from ajs.domain.scoring import match_score, status_for_score
from ajs.domain.status import ALLOWED, USER_ONLY, can_transition
from ajs.services.blob import BlobStore, UnsafePath, folder_name, slugify
from ajs.settings import Settings


def test_every_status_has_a_transition_entry() -> None:
    assert set(ALLOWED) == set(S)


def test_gate_transitions() -> None:
    assert can_transition(S.AWAITING_MATCH_REVIEW, S.MATCHED)
    assert can_transition(S.AWAITING_MATCH_REVIEW, S.MATCH_DECLINED)
    for s in S:
        if s is not S.AWAITING_MATCH_REVIEW:
            assert not can_transition(s, S.MATCH_DECLINED)
            assert not can_transition(s, S.MATCHED) or s is S.ERROR
    assert not can_transition(S.NEW, S.APPROVED)
    assert not can_transition(S.LOW_MATCH, S.AWAITING_MATCH_REVIEW)
    assert {S.MATCHED, S.APPROVED} <= USER_ONLY


def test_match_score_weights_and_bounds() -> None:
    assert match_score(100, 0, 0.4, 0.6) == 40
    assert match_score(0, 100, 0.4, 0.6) == 60
    assert match_score(50, 60, 2, 3) == 56  # weights are normalised
    with pytest.raises(ValueError):
        match_score(101, 0, 0.4, 0.6)


def test_threshold_is_inclusive() -> None:
    assert status_for_score(55, 55) is S.AWAITING_MATCH_REVIEW
    assert status_for_score(54.99, 55) is S.LOW_MATCH


@pytest.fixture
def store(tmp_path: Path) -> BlobStore:
    (tmp_path / "applications").mkdir()
    return BlobStore(Settings(data_root=tmp_path, host_data_root="C:\\dev\\JobSearchData"))


@pytest.mark.parametrize(
    "part", ["..", ".", "", "a/b", "a\\b", "/etc/passwd", "C:\\Windows", "C:evil", "x\0y"]
)
def test_blob_rejects_unsafe_segments(store: BlobStore, part: str) -> None:
    with pytest.raises(UnsafePath):
        store.resolve("ok", part)


def test_blob_rejects_symlink_escape(store: BlobStore, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (store.root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    with pytest.raises(UnsafePath):
        store.resolve("link", "file.md")


def test_blob_paths_and_host_mapping(store: BlobStore) -> None:
    path = store.write_text("2026-10_x_y_1", "cv_v1.md", "hi")
    assert store.relative(path) == "2026-10_x_y_1/cv_v1.md"
    assert store.read_text("2026-10_x_y_1/cv_v1.md") == "hi"
    assert store.host_path(path) == "C:\\dev\\JobSearchData\\applications\\2026-10_x_y_1\\cv_v1.md"


def test_folder_name() -> None:
    from datetime import datetime

    name = folder_name(datetime(2026, 10, 13), "Ørsted A/S", "Senior Dev / Lead", 42)
    assert name == "2026-10_rsted-a-s_senior-dev-lead_42"
    assert slugify("???") == "x"
