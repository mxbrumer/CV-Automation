"""Golden tests for the analyze_and_match flow (needs the running stack and Ollama)."""

import pytest

pytestmark = pytest.mark.llm

BRIEF_REQUIRED = (
    "title", "company", "language", "contact", "must_have", "nice_to_have", "keywords", "location",
    "relocation_ok", "required_languages", "danish_required", "company_values",
)  # fmt: skip


def assert_valid_brief(brief: dict) -> None:
    missing = [k for k in BRIEF_REQUIRED if k not in brief]
    assert not missing, f"job_brief lacks {missing}"
    assert brief["language"] in ("da", "en")
    for key in ("must_have", "nice_to_have", "keywords", "required_languages", "company_values"):
        assert isinstance(brief[key], list) and all(isinstance(x, str) for x in brief[key]), key
    assert brief["must_have"], "no must_have extracted"
    assert isinstance(brief["danish_required"], bool)
    assert len(brief["keywords"]) <= 25 and len(brief["company_values"]) <= 3
    assert brief["relocation_ok"] is None or isinstance(brief["relocation_ok"], bool)


def test_strong_english_match_awaits_review(strong: dict, threshold: float) -> None:
    assert strong["posting_language"] == "en"
    assert_valid_brief(strong["job_brief"])
    assert strong["job_brief"]["danish_required"] is False
    assert strong["embedding_score"] is not None and 0 <= strong["embedding_score"] <= 100
    assert strong["rubric_score"] is not None and 0 <= strong["rubric_score"] <= 100
    assert strong["match_score"] >= threshold
    assert strong["status"] == "awaiting_match_review"
    assert 0 < len(strong["match_rationale"].split()) <= 82  # <= 80 words (+ ellipsis)


def test_recruiter_contact_is_extracted(strong: dict) -> None:
    assert strong["recruiter_email"] == "freja.holm@nordlys-analytics.example"
    assert "Freja" in (strong["recruiter_name"] or "")


def test_weak_match_is_low_match(runner, threshold: float) -> None:
    posting = runner.analyze("en_weak_match.md")
    assert posting["posting_language"] == "en"
    assert_valid_brief(posting["job_brief"])
    assert posting["match_score"] < threshold
    assert posting["status"] == "low_match"


def test_danish_required_is_flagged_not_penalized(danish: dict, strong: dict, threshold: float) -> None:
    assert danish["posting_language"] == "da"
    assert_valid_brief(danish["job_brief"])
    brief = danish["job_brief"]
    assert brief["danish_required"] is True
    assert "da" in brief["required_languages"]
    # D10: the language requirement is a flag (the rubric drops language items before scoring),
    # so the score must stay close to the identical English posting.
    assert danish["status"] == ("awaiting_match_review" if danish["match_score"] >= threshold else "low_match")
    # The same role in English (no language requirement) must not score much higher: noise margin 20.
    assert danish["rubric_score"] >= strong["rubric_score"] - 20
    assert danish["match_score"] >= strong["match_score"] - 20


def test_unsupported_language_stops_without_llm(runner) -> None:
    posting = runner.analyze("de_unsupported.md")
    assert posting["status"] == "unsupported_language"
    assert posting["job_brief"] is None
    assert posting["match_score"] is None


def test_second_run_is_a_noop(runner, strong: dict) -> None:
    """One run per job: re-running a finished posting changes nothing."""
    before = runner.posting(strong["posting_id"])
    result = runner.run(strong["posting_id"])
    after = runner.posting(strong["posting_id"])
    assert "nothing to analyze" in str(result)
    assert (before["status"], before["match_score"], len(before["events"])) == (
        after["status"], after["match_score"], len(after["events"]),
    )  # fmt: skip
