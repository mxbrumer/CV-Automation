from typing import Any

import pytest
from fastapi.testclient import TestClient

from ajs.main import app
from ajs.settings import Settings

T = "/api/v1/tools"
U = "/api/v1"


def make_posting(client: TestClient, **over: Any) -> int:
    body = {
        "company": "Novo Nordisk A/S",
        "title": "Data Engineer",
        "source_job_id": "h1",
        "source_url": "https://www.jobindex.dk/vis-job/h1",
    } | over
    r = client.post(f"{T}/postings", json=body)
    assert r.status_code == 201, r.text
    return int(r.json()["posting_id"])


def to_review(client: TestClient, pid: int, emb: float = 80, rub: float = 80) -> None:
    r = client.patch(f"{T}/postings/{pid}/analysis", json={"language": "en", "job_brief": {}})
    assert r.status_code == 200, r.text
    r = client.patch(
        f"{T}/postings/{pid}/match",
        json={"embedding_score": emb, "rubric_score": rub, "rationale": "ok"},
    )
    assert r.status_code == 200, r.text


def to_queue(client: TestClient, pid: int) -> None:
    to_review(client, pid)
    client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "approve"})
    for to in ("generating", "generated"):
        assert client.post(f"{T}/postings/{pid}/status", json={"to": to}).status_code == 200
    assert client.post(f"{U}/postings/{pid}/approve").status_code == 200


# ---- auth -------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/stats", "/api/v1/tools/profile/cv-sections"])
def test_missing_or_wrong_key_is_401(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"X-API-Key": ""}).status_code == 401
    assert client.get(path, headers={"X-API-Key": "nope"}).status_code == 401


def test_unset_server_key_refuses_everything(client: TestClient) -> None:
    from ajs.settings import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(backend_api_key="")
    assert client.get(f"{U}/stats", headers={"X-API-Key": ""}).status_code == 401


def test_health_is_open(client: TestClient) -> None:
    assert client.get("/health", headers={"X-API-Key": ""}).status_code == 200


# ---- dedup (A5) -------------------------------------------------------------------------------


def find(client: TestClient, **body: Any) -> dict[str, Any]:
    r = client.post(f"{T}/postings/find", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_find_by_source_job_id_and_url(client: TestClient) -> None:
    pid = make_posting(client)
    hit = find(client, company="Other", title="Other", source_job_id="h1")
    assert hit["exists"] and hit["posting_id"] == pid
    hit = find(
        client, company="Other", title="Other", source_url="https://www.jobindex.dk/vis-job/h1"
    )
    assert hit["exists"] and hit["posting_id"] == pid


def test_find_fuzzy_match(client: TestClient) -> None:
    pid = make_posting(client, title="Senior Data Engineer (m/f)")
    hit = find(client, company="NOVO NORDISK", title="Senior Data Engineer", source_job_id="h2")
    assert hit["exists"] and hit["posting_id"] == pid


def test_find_no_match(client: TestClient) -> None:
    make_posting(client)
    assert not find(client, company="Novo Nordisk", title="Marketing Manager")["exists"]
    assert not find(client, company="Maersk", title="Data Engineer")["exists"]


def test_create_duplicate_source_id_conflicts(client: TestClient) -> None:
    make_posting(client)
    r = client.post(f"{T}/postings", json={"company": "X", "title": "Y", "source_job_id": "h1"})
    assert r.status_code == 409


# ---- Add job (plan 15, D3) -------------------------------------------------------------------

JOB = {
    "company": "Novo Nordisk A/S",
    "title": "Data Engineer",
    "url": "https://careers.novonordisk.com/job/42",
    "text": "We are looking for a data engineer. " * 40,
}


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr("ajs.api.ui.postings.run_pipeline", lambda *a: calls.append(a))
    return calls


def test_add_job_stores_a_manual_posting_and_starts_analysis(
    client: TestClient, queued: list[tuple[Any, ...]]
) -> None:
    r = client.post(f"{U}/postings", json=JOB)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["company"], body["source_url"]) == (
        "new",
        "Novo Nordisk A/S",
        JOB["url"],
    )
    detail = client.get(f"{U}/postings/{body['posting_id']}").json()
    assert detail["posting_text"] == JOB["text"].strip()
    assert [e["to_status"] for e in detail["events"]] == ["new"]
    assert len(queued) == 1  # the analysis run is queued at once


def test_add_job_without_url(client: TestClient, queued: list[tuple[Any, ...]]) -> None:
    r = client.post(f"{U}/postings", json=JOB | {"url": "  "})
    assert r.status_code == 201, r.text
    assert r.json()["source_url"] is None


def test_add_job_same_url_is_refused_even_with_force(
    client: TestClient, queued: list[tuple[Any, ...]]
) -> None:
    first = client.post(f"{U}/postings", json=JOB).json()
    other = JOB | {"company": "Maersk", "title": "Marketing Manager"}
    for force in (False, True):
        r = client.post(f"{U}/postings", json=other | {"force": force})
        assert r.status_code == 409, r.text
        assert r.json()["reason"] == "same_url"
        assert r.json()["posting"]["posting_id"] == first["posting_id"]
    assert len(queued) == 1


def test_add_job_url_of_a_duplicate_row_is_refused(
    client: TestClient, queued: list[tuple[Any, ...]]
) -> None:
    pid = make_posting(client, source_url=JOB["url"])
    assert client.post(f"{T}/postings/{pid}/status", json={"to": "duplicate"}).status_code == 200
    r = client.post(f"{U}/postings", json=JOB | {"company": "Maersk", "force": True})
    assert r.status_code == 409 and r.json()["reason"] == "same_url"
    assert r.json()["posting"]["posting_id"] == pid


def test_add_job_similar_asks_then_force_adds(
    client: TestClient, queued: list[tuple[Any, ...]]
) -> None:
    first = client.post(f"{U}/postings", json=JOB).json()
    again = JOB | {"company": "NOVO NORDISK", "url": None}
    r = client.post(f"{U}/postings", json=again)
    assert r.status_code == 409 and r.json()["reason"] == "similar"
    assert r.json()["posting"]["posting_id"] == first["posting_id"]
    r = client.post(f"{U}/postings", json=again | {"force": True})
    assert r.status_code == 201, r.text
    assert r.json()["posting_id"] != first["posting_id"]
    assert len(queued) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"company": " "},
        {"title": ""},
        {"text": "   "},
        {"url": "ftp://example.com/job"},
        {"url": "careers.example.com/job"},
    ],
)
def test_add_job_validation(
    client: TestClient, queued: list[tuple[Any, ...]], change: dict[str, Any]
) -> None:
    assert client.post(f"{U}/postings", json=JOB | change).status_code == 422
    body = {k: v for k, v in JOB.items() if k != "text"}
    assert client.post(f"{U}/postings", json=body).status_code == 422
    assert queued == []


def test_process_pending_queues_a_run(client: TestClient, queued: list[tuple[Any, ...]]) -> None:
    r = client.post(f"{U}/workflow/process-pending")
    assert r.status_code == 202 and len(queued) == 1
    assert client.post(f"{U}/workflow/poll").status_code == 404


# ---- match score and gate 1 -------------------------------------------------------------------


def test_match_score_math_and_threshold(client: TestClient) -> None:
    hi = make_posting(client, source_job_id="a", source_url=None, title="A")
    lo = make_posting(client, source_job_id="b", source_url=None, title="B")
    for pid in (hi, lo):
        client.patch(f"{T}/postings/{pid}/analysis", json={"language": "en", "job_brief": {}})
    r = client.patch(
        f"{T}/postings/{hi}/match",
        json={"embedding_score": 50, "rubric_score": 60, "rationale": "r"},
    )
    assert r.json()["match_score"] == 56.0  # 0.4*50 + 0.6*60
    assert r.json()["status"] == "awaiting_match_review"
    r = client.patch(
        f"{T}/postings/{lo}/match",
        json={"embedding_score": 50, "rubric_score": 58, "rationale": "r"},
    )
    assert r.json()["match_score"] == 54.8
    assert r.json()["status"] == "low_match"


def test_match_requires_analyzed_status(client: TestClient) -> None:
    pid = make_posting(client)
    r = client.patch(
        f"{T}/postings/{pid}/match",
        json={"embedding_score": 90, "rubric_score": 90, "rationale": "r"},
    )
    assert r.status_code == 409


def test_gate1_only_awaiting_match_review_accepts_decision(client: TestClient) -> None:
    pid = make_posting(client)
    r = client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "approve"})
    assert r.status_code == 409  # still `new`
    to_review(client, pid)
    r = client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "matched"
    r = client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "decline"})
    assert r.status_code == 409  # already decided


def test_gate1_decline_is_terminal(client: TestClient) -> None:
    pid = make_posting(client)
    to_review(client, pid)
    r = client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "decline"})
    assert r.json()["status"] == "match_declined"
    assert client.post(f"{T}/postings/{pid}/status", json={"to": "new"}).status_code == 409


def test_tools_cannot_make_user_decisions(client: TestClient) -> None:
    pid = make_posting(client)
    to_review(client, pid)
    assert client.post(f"{T}/postings/{pid}/status", json={"to": "matched"}).status_code == 403


def test_every_change_writes_an_event(client: TestClient) -> None:
    pid = make_posting(client)
    to_review(client, pid)
    events = client.get(f"{U}/postings/{pid}").json()["events"]
    assert [e["to_status"] for e in events] == ["new", "analyzed", "awaiting_match_review"]


# ---- queue ------------------------------------------------------------------------------------


def test_queue_order_and_skip(client: TestClient) -> None:
    ids = [
        make_posting(client, source_job_id=f"q{i}", source_url=None, title=f"T{i}")
        for i in range(3)
    ]
    assert client.get(f"{U}/queue/next").json() is None
    for pid in ids:
        to_queue(client, pid)
    assert client.get(f"{U}/queue/next").json()["posting_id"] == ids[0]

    client.post(f"{U}/queue/{ids[0]}/action", json={"action": "skip"})
    assert client.get(f"{U}/queue/next").json()["posting_id"] == ids[1]
    assert client.get(f"{U}/postings/{ids[0]}").json()["status"] == "approved"  # skip: no change

    client.post(f"{U}/queue/{ids[1]}/action", json={"action": "submitted"})
    assert client.get(f"{U}/queue/next").json()["posting_id"] == ids[2]
    client.post(f"{U}/queue/{ids[2]}/action", json={"action": "declined"})
    head = client.get(f"{U}/queue/next").json()
    assert head["posting_id"] == ids[0]  # the skipped one is last, then alone
    assert client.get(f"{U}/postings/{ids[1]}").json()["status"] == "submitted"
    assert client.get(f"{U}/postings/{ids[2]}").json()["status"] == "declined"


def test_queue_decline_keeps_reason(client: TestClient) -> None:
    pid = make_posting(client, source_job_id="qn", source_url=None)
    to_queue(client, pid)
    client.post(f"{U}/queue/{pid}/action", json={"action": "declined", "note": "too far"})
    events = client.get(f"{U}/postings/{pid}").json()["events"]
    assert events[-1]["note"] == "queue: declined - too far"


def test_queue_action_requires_queued_posting(client: TestClient) -> None:
    pid = make_posting(client)
    r = client.post(f"{U}/queue/{pid}/action", json={"action": "submitted"})
    assert r.status_code == 409


# ---- stats, listing, artifacts, files ---------------------------------------------------------


def test_stats_and_listing(client: TestClient) -> None:
    pid = make_posting(client)
    to_review(client, pid, 90, 90)
    other = make_posting(
        client, company="Maersk", title="Analyst", source_job_id="z", source_url=None
    )
    assert client.get(f"{U}/stats").json() == {
        "reviewed": 2,
        "awaiting_match_review": 1,
        "good_match": 1,
    }
    page = client.get(f"{U}/postings", params={"status": "awaiting_match_review"}).json()
    assert [i["posting_id"] for i in page["items"]] == [pid] and page["total"] == 1
    page = client.get(f"{U}/postings", params={"q": "maersk"}).json()
    assert [i["posting_id"] for i in page["items"]] == [other]
    page = client.get(f"{U}/postings", params={"sort": "recent"}).json()
    assert [i["posting_id"] for i in page["items"]] == [other, pid]
    assert client.get(f"{U}/postings/9999").status_code == 404
    assert client.get(f"{U}/workflow/last-run").json() is None


def test_artifact_versions_and_files(client: TestClient, settings: Any) -> None:
    pid = make_posting(client)
    folder = client.post(f"{T}/postings/{pid}/folder").json()["path"]
    assert folder.endswith(f"_novo-nordisk-a-s_data-engineer_{pid}")
    r = client.post(f"{T}/postings/{pid}/artifacts", json={"kind": "cv", "markdown": "# CV v1"})
    assert r.status_code == 201 and r.json()["version"] == 1
    # A PDF exists wherever WeasyPrint's system libraries do (CI, Docker), not on the Windows host.
    name = folder.rsplit("/", 1)[-1]
    assert r.json()["md_path"] == f"{name}/CV_Novo_Nordisk_A_S.md"
    assert r.json()["pdf_path"] in (None, f"{name}/CV_Novo_Nordisk_A_S.pdf")
    r = client.put(f"{U}/postings/{pid}/artifacts/cv", json={"markdown": "# CV v2"})
    assert r.json()["version"] == 2 and r.json()["markdown"] == "# CV v2"
    assert client.get(f"{U}/postings/{pid}/artifacts/cv").json()["markdown"] == "# CV v2"
    assert client.get(f"{U}/postings/{pid}/artifacts/cover_letter").status_code == 404
    # The latest version keeps the clean name; the one it replaced moved to versions/.
    assert client.get(f"{U}/files/{pid}/CV_Novo_Nordisk_A_S.md").text == "# CV v2"
    old = client.get(f"{U}/postings/{pid}/artifacts/cv", params={"version": 1}).json()
    assert old["md_path"] == f"{name}/versions/CV_Novo_Nordisk_A_S_v1.md"
    assert client.get(f"{U}/files/{pid}/versions/CV_Novo_Nordisk_A_S_v1.md").text == "# CV v1"
    assert client.get(f"{U}/files/{pid}/versions/..%2F..%2F..%2Fsecret").status_code == 400
    assert client.get(f"{U}/files/{pid}/nope.pdf").status_code == 404
    assert client.get(f"{U}/files/{pid}/..%2F..%2Fsecret").status_code in (400, 404)


def test_profile_endpoints(client: TestClient, settings: Any) -> None:
    assert client.get(f"{T}/profile/cv-sections").status_code == 404
    (settings.profile_root / "cv.md").write_text(
        "# Name\nintro\n\n## Skills\npython\n\n## Skills\nmore\n\n## Experience\nx",
        encoding="utf-8",
    )
    sections = client.get(f"{T}/profile/cv-sections").json()
    assert [s["id"] for s in sections] == ["preamble", "skills", "skills-2", "experience"]
    assert sections[1]["markdown"].startswith("## Skills")
    (settings.profile_root / "recruiter_email_template.md").write_text(
        "Hi {{ name }}", encoding="utf-8"
    )
    assert (
        client.get(f"{T}/profile/templates/recruiter_email").json()["markdown"] == "Hi {{ name }}"
    )
    assert client.get(f"{T}/profile/templates/cover_letter").status_code == 404
    assert client.get(f"{T}/profile/templates/other").status_code == 422


def test_workflow_run_without_flow_id_is_503(client: TestClient, settings: Settings) -> None:
    settings.langflow_generation_flow_id = ""
    assert client.post(f"{U}/workflow/run", json={"phase": "generation"}).status_code == 503


# ---- review: chat editing (plan 12) -----------------------------------------------------------


class FakeLLM:
    def __init__(self, reply: str = "", fail: bool = False) -> None:
        self.reply, self.fail = reply, fail
        self.seen: list[list[dict[str, str]]] = []

    def stream(self, messages: list[dict[str, str]]) -> Any:
        self.seen.append(messages)
        if self.fail:
            raise ConnectionError("ollama is down")
        for i in range(0, len(self.reply), 12):
            yield self.reply[i : i + 12]


def use_llm(llm: FakeLLM) -> None:
    from ajs.api.ui.chat import get_chat_llm

    app.dependency_overrides[get_chat_llm] = lambda: llm


def generated_posting(client: TestClient, settings: Settings) -> int:
    pid = make_posting(client)
    to_review(client, pid)
    client.post(f"{U}/postings/{pid}/match-decision", json={"decision": "approve"})
    for to in ("generating", "generated"):
        client.post(f"{T}/postings/{pid}/status", json={"to": to})
    client.post(f"{T}/postings/{pid}/artifacts", json={"kind": "cv", "markdown": "# CV v1"})
    (settings.profile_root / "cv.md").write_text("# Max\nPython, SQL", encoding="utf-8")
    return pid


def sse_events(text: str) -> list[tuple[str, Any]]:
    import json

    out = []
    for block in text.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_chat_round_trip_creates_v2(client: TestClient, settings: Settings) -> None:
    pid = generated_posting(client, settings)
    llm = FakeLLM("EXPLANATION: Shortened the intro.\n<document>\n# CV v2 shorter\n</document>")
    use_llm(llm)
    r = client.post(f"{U}/postings/{pid}/artifacts/cv/chat", json={"message": "shorter"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert events[0][0] == "delta" and events[-1][0] == "done"
    message = events[-1][1]["message"]
    assert message["content"] == "Shortened the intro."
    assert message["proposal"] == "# CV v2 shorter"
    system = llm.seen[0][0]["content"]
    assert "Python, SQL" in system and "# CV v1" in system  # CV evidence and current document
    assert llm.seen[0][-1] == {"role": "user", "content": "shorter"}

    history = client.get(f"{U}/postings/{pid}/artifacts/cv/chat").json()
    assert [m["role"] for m in history] == ["user", "assistant"]

    r = client.post(
        f"{U}/postings/{pid}/artifacts/cv/chat/accept", json={"message_id": message["message_id"]}
    )
    assert r.status_code == 200 and r.json()["version"] == 2
    assert r.json()["markdown"] == "# CV v2 shorter"
    assert client.get(f"{U}/postings/{pid}/artifacts/cv").json()["version"] == 2
    assert client.get(f"{U}/postings/{pid}/artifacts/cv?version=1").json()["markdown"] == "# CV v1"
    assert client.get(f"{U}/postings/{pid}/artifacts/cv?version=9").status_code == 404


def test_chat_question_has_no_proposal_and_cannot_be_accepted(
    client: TestClient, settings: Settings
) -> None:
    pid = generated_posting(client, settings)
    use_llm(FakeLLM("EXPLANATION: The CV does not mention Rust."))
    r = client.post(f"{U}/postings/{pid}/artifacts/cv/chat", json={"message": "add Rust"})
    message = sse_events(r.text)[-1][1]["message"]
    assert message["proposal"] is None
    r = client.post(
        f"{U}/postings/{pid}/artifacts/cv/chat/accept", json={"message_id": message["message_id"]}
    )
    assert r.status_code == 409


def test_chat_model_failure_is_an_error_event_and_keeps_user_turn(
    client: TestClient, settings: Settings
) -> None:
    pid = generated_posting(client, settings)
    use_llm(FakeLLM(fail=True))
    r = client.post(f"{U}/postings/{pid}/artifacts/cv/chat", json={"message": "shorter"})
    assert r.status_code == 200
    assert sse_events(r.text) == [("error", {"detail": "model call failed: ollama is down"})]
    assert [m["role"] for m in client.get(f"{U}/postings/{pid}/artifacts/cv/chat").json()] == [
        "user"
    ]


def test_chat_accept_rejects_foreign_messages(client: TestClient, settings: Settings) -> None:
    pid = generated_posting(client, settings)
    use_llm(FakeLLM("EXPLANATION: ok\n<document>\n# x\n</document>"))
    client.post(f"{U}/postings/{pid}/artifacts/cv/chat", json={"message": "x"})
    history = client.get(f"{U}/postings/{pid}/artifacts/cv/chat").json()
    user_id, assistant_id = history[0]["message_id"], history[1]["message_id"]
    accept = f"{U}/postings/{pid}/artifacts/cv/chat/accept"
    assert client.post(accept, json={"message_id": user_id}).status_code == 404
    other = f"{U}/postings/{pid}/artifacts/cover_letter/chat/accept"
    assert client.post(other, json={"message_id": assistant_id}).status_code == 404
    assert (
        client.post(f"{U}/postings/{pid}/artifacts/nope/chat", json={"message": "x"}).status_code
        == 422
    )


def test_chat_without_artifact_is_404(client: TestClient, settings: Settings) -> None:
    pid = make_posting(client)
    use_llm(FakeLLM("EXPLANATION: x"))
    r = client.post(f"{U}/postings/{pid}/artifacts/cv/chat", json={"message": "x"})
    assert r.status_code == 404


def test_reject_generated_posting(client: TestClient, settings: Settings) -> None:
    pid = generated_posting(client, settings)
    r = client.post(f"{U}/postings/{pid}/reject", json={"note": "not for me"})
    assert r.json()["status"] == "declined"
    assert client.post(f"{U}/postings/{pid}/reject", json={}).status_code == 409


def test_parse_reply_variants() -> None:
    from ajs.services.chat import parse_reply

    assert parse_reply("EXPLANATION: a\n<document>\nB\n</document>").markdown == "B"
    assert parse_reply("EXPLANATION: a\n<document>\nB").markdown == "B"  # cut off before the tag
    assert parse_reply("no markers at all").explanation == "no markers at all"
    assert parse_reply("EXPLANATION: just talk").markdown is None
