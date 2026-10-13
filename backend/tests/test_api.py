from typing import Any

import pytest
from fastapi.testclient import TestClient

from ajs.main import app

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
    assert client.get(f"{U}/postings/9999").status_code == 404


def test_artifact_versions_and_files(client: TestClient, settings: Any) -> None:
    pid = make_posting(client)
    folder = client.post(f"{T}/postings/{pid}/folder").json()["path"]
    assert folder.endswith(f"_novo-nordisk-a-s_data-engineer_{pid}")
    r = client.post(f"{T}/postings/{pid}/artifacts", json={"kind": "cv", "markdown": "# CV v1"})
    assert r.status_code == 201 and r.json()["version"] == 1 and r.json()["pdf_path"] is None
    r = client.put(f"{U}/postings/{pid}/artifacts/cv", json={"markdown": "# CV v2"})
    assert r.json()["version"] == 2 and r.json()["markdown"] == "# CV v2"
    assert client.get(f"{U}/postings/{pid}/artifacts/cv").json()["markdown"] == "# CV v2"
    assert client.get(f"{U}/postings/{pid}/artifacts/cover_letter").status_code == 404
    assert client.get(f"{U}/files/{pid}/cv_v1.md").text == "# CV v1"
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


def test_workflow_run_without_flow_id_is_503(client: TestClient) -> None:
    assert client.post(f"{U}/workflow/run", json={"phase": "analysis"}).status_code == 503
