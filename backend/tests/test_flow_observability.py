"""Plan 10: egress guard, run records with trace links, and telemetry switch."""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ajs.db.models import FactPosting, PostingStatus, WorkflowRun
from ajs.services.egress import EgressBlocked, egress_hook
from ajs.services.langflow_client import FlowRef, LangflowClient
from ajs.settings import Settings
from ajs.telemetry import setup_telemetry
from ajs.worker.pipeline import FlowError, Pipeline
from test_intake import FakeFetcher, FakeFlows, FakeSource, raw


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1/chat",
        "https://api.anthropic.com/v1/messages",
        "https://x.groq.com/",
    ],
)
def test_hosted_llm_hosts_are_refused(url: str) -> None:
    with pytest.raises(EgressBlocked):
        egress_hook("test")(httpx.Request("POST", url))


def test_public_job_pages_pass_and_pinned_clients_refuse_others() -> None:
    egress_hook("fetcher")(httpx.Request("GET", "https://www.jobindex.dk/vis-job/1"))
    pinned = egress_hook("langflow", {"langflow"})
    pinned(httpx.Request("POST", "http://langflow:7860/api/v1/run/x"))
    with pytest.raises(EgressBlocked):
        pinned(httpx.Request("GET", "https://example.com/"))


def test_langflow_client_sends_a_session_id(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"outputs": []})

    client = LangflowClient(
        settings,
        httpx.Client(base_url=settings.langflow_url, transport=httpx.MockTransport(handler)),
    )
    ref = client.run_flow("analyze_and_match", '{"posting_id": 1}')
    assert ref.session_id.startswith("ajs-") and json.loads(
        json.loads(seen[0].content)["input_value"]
    ) == {
        "posting_id": 1,
        "ajs_session": ref.session_id,
    }
    assert (
        LangflowClient(
            settings,
            httpx.Client(base_url=settings.langflow_url, transport=httpx.MockTransport(handler)),
        )
        .run_flow("f", "{}", session_id="mine")
        .session_id
        == "mine"
    )


class RefFlows(FakeFlows):
    def run(self, phase: str, posting_id: int) -> FlowRef | None:
        super().run(phase, posting_id)
        return FlowRef("ajs-abc", "0" * 31 + "1")


def test_pipeline_records_workflow_runs(db: Session, settings: Settings) -> None:
    flows = RefFlows(db)
    pipe = Pipeline(
        db, settings, FakeSource([raw("o-1")]), FakeFetcher(), flows, sleep=lambda s: None
    )
    pipe.run_analysis()
    posting = db.scalars(select(FactPosting).where(FactPosting.source_job_id == "o-1")).one()
    assert posting.status is PostingStatus.AWAITING_MATCH_REVIEW
    run = db.scalars(select(WorkflowRun).where(WorkflowRun.posting_id == posting.posting_id)).one()
    assert (run.phase, run.status) == ("analysis", "succeeded")
    assert run.langflow_run_id == "ajs-abc" and run.phoenix_trace_id == "0" * 31 + "1"
    assert run.finished_at is not None


def test_failed_flow_is_recorded(db: Session, settings: Settings) -> None:
    flows = FakeFlows(db)
    flows.error = FlowError("boom")
    pipe = Pipeline(
        db, settings, FakeSource([raw("o-2")]), FakeFetcher(), flows, sleep=lambda s: None
    )
    pipe.run_analysis()
    run = db.scalars(select(WorkflowRun).order_by(WorkflowRun.run_id.desc())).first()
    assert run is not None and run.status == "failed" and run.error == "boom"


def test_telemetry_is_off_without_endpoint(settings: Settings) -> None:
    assert settings.phoenix_collector_endpoint == ""
    assert setup_telemetry(settings, "test") is False
