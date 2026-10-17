"""Pipeline runner with stubbed flows: analysis of pending postings, retries and generation."""

from sqlalchemy.orm import Session

from ajs.db.models import Actor, FactPosting, PostingStatus
from ajs.domain.status import transition
from ajs.services import postings
from ajs.services.langflow_client import FlowRef
from ajs.services.pipeline import FlowError, Pipeline
from ajs.settings import Settings


class FakeFlows:
    """Stands in for LangFlow: moves the posting the way plan 08's flow does."""

    def __init__(
        self, session: Session, outcome: PostingStatus = PostingStatus.AWAITING_MATCH_REVIEW
    ) -> None:
        self.session, self.outcome = session, outcome
        self.runs: list[tuple[str, int]] = []
        self.error: FlowError | None = None
        self.configured = True

    def available(self, phase: str) -> bool:
        return self.configured

    def run(self, phase: str, posting_id: int) -> FlowRef | None:
        self.runs.append((phase, posting_id))
        if self.error is not None:
            raise self.error
        posting = self.session.get(FactPosting, posting_id)
        assert posting is not None
        if phase == "analysis":
            transition(self.session, posting, PostingStatus.ANALYZED, Actor.AGENT)
            transition(self.session, posting, self.outcome, Actor.AGENT)
        else:
            transition(self.session, posting, PostingStatus.GENERATING, Actor.AGENT)
            transition(self.session, posting, PostingStatus.GENERATED, Actor.AGENT)
        self.session.commit()
        return None


def add(
    db: Session,
    title: str = "Data Analyst",
    company: str = "Acme A/S",
    text: str | None = "A full posting text.",
) -> FactPosting:
    posting = postings.create_posting(
        db, company=company, title=title, source="manual", posting_text=text
    )
    db.commit()
    return posting


def pipeline(db: Session, settings: Settings, flows: FakeFlows | None = None) -> Pipeline:
    return Pipeline(db, settings, flows or FakeFlows(db), sleep=lambda s: None)


def test_analysis_stops_at_awaiting_match_review(db: Session, settings: Settings) -> None:
    posting = add(db)
    flows = FakeFlows(db)
    summary = pipeline(db, settings, flows).analyze_pending()
    assert posting.status is PostingStatus.AWAITING_MATCH_REVIEW and summary.analyzed == 1
    assert flows.runs == [("analysis", posting.posting_id)]  # generation is not started


def test_low_match_is_terminal(db: Session, settings: Settings) -> None:
    posting = add(db)
    flows = FakeFlows(db, outcome=PostingStatus.LOW_MATCH)
    pipeline(db, settings, flows).analyze_pending()
    assert posting.status is PostingStatus.LOW_MATCH
    assert [p for p, _ in flows.runs] == ["analysis"]


def test_postings_without_text_are_skipped(db: Session, settings: Settings) -> None:
    posting = add(db, text=None)
    flows = FakeFlows(db)
    pipeline(db, settings, flows).analyze_pending()
    assert posting.status is PostingStatus.NEW and flows.runs == []


def test_posting_added_during_a_run_is_analyzed(db: Session, settings: Settings) -> None:
    """A submit while the lock is held skips its own run; the running one picks it up."""
    first = add(db)
    added: list[FactPosting] = []

    class AddingFlows(FakeFlows):
        def run(self, phase: str, posting_id: int) -> FlowRef | None:
            if not added:
                added.append(add(db, "Other Role", "Other Co"))
            return super().run(phase, posting_id)

    flows = AddingFlows(db)
    summary = pipeline(db, settings, flows).analyze_pending()
    assert [pid for _, pid in flows.runs] == [first.posting_id, added[0].posting_id]
    assert summary.analyzed == 2


def test_transient_flow_error_is_retried_then_recorded(db: Session, settings: Settings) -> None:
    posting = add(db)
    flows = FakeFlows(db)
    flows.error = FlowError("timeout", transient=True)
    summary = pipeline(db, settings, flows).analyze_pending()
    assert len(flows.runs) == 3  # first try + 2 retries
    assert posting.status is PostingStatus.ERROR and summary.errors == 1


def test_permanent_flow_error_is_not_retried_and_isolated(db: Session, settings: Settings) -> None:
    add(db)
    second = add(db, "Other Role", "Other Co")
    flows = FakeFlows(db)
    flows.error = FlowError("bad request", transient=False)
    summary = pipeline(db, settings, flows).analyze_pending()
    assert len(flows.runs) == 2  # one try per posting; the first error did not stop the second
    assert second.status is PostingStatus.ERROR and summary.errors == 2


def test_generation_runs_only_for_matched_postings(db: Session, settings: Settings) -> None:
    approved, other = add(db), add(db, "Other Role", "Other Co")
    pipe = pipeline(db, settings, flows := FakeFlows(db))
    pipe.analyze_pending()
    transition(db, approved, PostingStatus.MATCHED, Actor.USER)  # gate 1 (D9)
    db.commit()
    summary = pipe.run_generation()
    assert [r for r in flows.runs if r[0] == "generation"] == [("generation", approved.posting_id)]
    assert summary.generated == 1
    assert other.status is PostingStatus.AWAITING_MATCH_REVIEW


def test_run_all_drains_both_phases_including_late_arrivals(
    db: Session, settings: Settings
) -> None:
    """An approval or a submit while the run holds the lock is picked up by that run."""
    approved = add(db)
    pipeline(db, settings).analyze_pending()
    transition(db, approved, PostingStatus.MATCHED, Actor.USER)
    db.commit()
    late: list[FactPosting] = []

    class LateFlows(FakeFlows):
        def run(self, phase: str, posting_id: int) -> FlowRef | None:
            ref = super().run(phase, posting_id)
            if phase == "generation" and not late:  # a job submitted during generation
                late.append(add(db, "Other Role", "Other Co"))
            elif phase == "analysis" and posting_id == late[0].posting_id:
                transition(db, late[0], PostingStatus.MATCHED, Actor.USER)  # and approved
                db.commit()
            return ref

    flows = LateFlows(db)
    summary = pipeline(db, settings, flows).run_all()
    assert flows.runs == [
        ("generation", approved.posting_id),
        ("analysis", late[0].posting_id),
        ("generation", late[0].posting_id),
    ]
    assert summary.generated == 2 and summary.analyzed == 1
    assert late[0].status is PostingStatus.GENERATED


def test_unconfigured_flow_leaves_postings_new(db: Session, settings: Settings) -> None:
    posting = add(db)
    flows = FakeFlows(db)
    flows.configured = False
    summary = pipeline(db, settings, flows).analyze_pending()
    assert posting.status is PostingStatus.NEW and flows.runs == []
    assert summary.notes
