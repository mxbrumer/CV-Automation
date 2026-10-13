"""Hybrid match score (D8): 0-100 = w_e * embedding + w_r * rubric."""

from ajs.db.models import PostingStatus


def match_score(embedding: float, rubric: float, w_embedding: float, w_rubric: float) -> float:
    for name, value in (("embedding", embedding), ("rubric", rubric)):
        if not 0 <= value <= 100:
            raise ValueError(f"{name} score must be between 0 and 100, got {value}")
    total = w_embedding + w_rubric
    if total <= 0:
        raise ValueError("score weights must sum to a positive number")
    return round((w_embedding * embedding + w_rubric * rubric) / total, 2)


def status_for_score(score: float, threshold: float) -> PostingStatus:
    """At or above the threshold waits for gate 1; below it is a terminal `low_match`."""
    return PostingStatus.AWAITING_MATCH_REVIEW if score >= threshold else PostingStatus.LOW_MATCH
