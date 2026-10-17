"""Posting status lifecycle (architecture §6). Every change goes through `transition`."""

from sqlalchemy.orm import Session

from ajs.db.models import Actor, FactPosting, PostingEvent
from ajs.db.models import PostingStatus as S

ALLOWED: dict[S, frozenset[S]] = {
    S.NEW: frozenset({S.ANALYZED, S.DUPLICATE, S.UNSUPPORTED_LANGUAGE, S.ERROR}),
    S.ANALYZED: frozenset({S.LOW_MATCH, S.AWAITING_MATCH_REVIEW, S.UNSUPPORTED_LANGUAGE, S.ERROR}),
    S.LOW_MATCH: frozenset(),
    S.AWAITING_MATCH_REVIEW: frozenset({S.MATCHED, S.MATCH_DECLINED}),  # gate 1 (D9)
    S.MATCH_DECLINED: frozenset(),
    S.MATCHED: frozenset({S.GENERATING, S.ERROR}),
    S.GENERATING: frozenset({S.GENERATED, S.ERROR}),
    S.GENERATED: frozenset({S.APPROVED, S.DECLINED, S.GENERATING, S.ERROR}),  # gate 2
    S.APPROVED: frozenset({S.SUBMITTED, S.DECLINED}),
    S.SUBMITTED: frozenset(),
    S.DECLINED: frozenset(),
    S.DUPLICATE: frozenset(),
    S.NEEDS_MANUAL_TEXT: frozenset({S.NEW, S.ERROR}),  # no longer set (D3); keeps the map total
    S.UNSUPPORTED_LANGUAGE: frozenset(),
    S.ERROR: frozenset({S.NEW, S.MATCHED}),  # retry after a failed analysis / generation
}

# Decisions that only the user may make; the tool endpoints used by LangFlow refuse them.
USER_ONLY: frozenset[S] = frozenset(
    {S.MATCHED, S.MATCH_DECLINED, S.APPROVED, S.SUBMITTED, S.DECLINED}
)


class InvalidTransition(Exception):
    def __init__(self, current: S, to: S) -> None:
        super().__init__(f"cannot change status from '{current.value}' to '{to.value}'")
        self.current = current
        self.to = to


def can_transition(current: S, to: S) -> bool:
    return to in ALLOWED[current]


def transition(
    session: Session, posting: FactPosting, to: S, actor: Actor, note: str | None = None
) -> PostingEvent:
    """Change `posting.status` and write the `posting_event` row, or raise InvalidTransition."""
    current = posting.status
    if not can_transition(current, to):
        raise InvalidTransition(current, to)
    posting.status = to
    event = PostingEvent(
        posting_id=posting.posting_id, from_status=current, to_status=to, actor=actor, note=note
    )
    session.add(event)
    session.flush()
    return event
