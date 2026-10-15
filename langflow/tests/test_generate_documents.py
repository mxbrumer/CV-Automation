"""Golden tests for the `generate_documents` flow (plan 09). Marked `llm`: they need the running
stack and native Ollama (see conftest.py for how to run them).

The postings are synthetic: a hand-written job_brief is saved through the tool endpoints and the
posting is approved at gate 1, so no analysis run is needed.
"""

import json
import os
import re
import uuid
from pathlib import Path

import httpx
import pytest
from conftest import REPO, dotenv

pytestmark = pytest.mark.llm
FLOW = os.environ.get("LANGFLOW_GENERATION_FLOW_ID") or "generate_documents"
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
PROFILE = Path(dotenv("DATA_ROOT") or r"C:\dev\JobSearchData") / "profile"
DANISH_WORDS = re.compile(r"\b(og|til|med|som|er|vi|du|af|jeres|stilling|erfaring)\b", re.IGNORECASE)

EN_BRIEF = {
    "title": "LLM Platform Engineer",
    "company": "Golden Test Generation EN",
    "language": "en",
    "must_have": [
        "Experience building data pipelines with Airflow or similar orchestration",
        "Experience shipping LLM or agentic AI workflows to production",
        "Python and SQL",
    ],
    "nice_to_have": ["Experience with AI governance or observability"],
    "keywords": ["LLM", "agents", "Airflow", "Python", "observability"],
    "location": "Aarhus",
    "relocation_ok": True,
    "required_languages": ["en"],
    "danish_required": False,
    "company_values": ["Transparency", "Ownership"],
    "contact": {"name": "Maja Jensen", "role": "Talent Partner", "email": "maja@example.com", "phone": None},
}
DA_BRIEF = {
    **EN_BRIEF,
    "title": "Dataingeniør til AI-platform",
    "company": "Golden Test Generation DA",
    "language": "da",
    "must_have": [
        "Erfaring med at bygge datapipelines med Airflow eller lignende",
        "Erfaring med at sætte LLM-løsninger i produktion",
        "Gode kompetencer i Python og SQL",
    ],
    "nice_to_have": ["Kendskab til AI-governance"],
    "keywords": ["datapipelines", "LLM", "Python"],
    "company_values": ["Samarbejde", "Tillid"],
    "contact": None,
}


def matched_posting(backend: httpx.Client, brief: dict, text: str) -> int:
    created = backend.post(
        "/tools/postings",
        json={
            "company": brief["company"],
            "title": brief["title"],
            "source": "golden-test",
            "source_job_id": uuid.uuid4().hex,
            "posting_text": text,
        },
    )
    created.raise_for_status()
    posting_id = created.json()["posting_id"]
    contact = brief.get("contact") or {}
    backend.patch(
        f"/tools/postings/{posting_id}/analysis",
        json={
            "language": brief["language"],
            "recruiter_name": contact.get("name"),
            "recruiter_email": contact.get("email"),
            "job_brief": brief,
        },
    ).raise_for_status()
    backend.patch(
        f"/tools/postings/{posting_id}/match",
        json={"embedding_score": 80, "rubric_score": 80, "rationale": "Synthetic strong match."},
    ).raise_for_status()
    backend.post(f"/postings/{posting_id}/match-decision", json={"decision": "approve"}).raise_for_status()
    return posting_id


def generate(backend: httpx.Client, langflow: httpx.Client, brief: dict, text: str) -> tuple[int, dict]:
    posting_id = matched_posting(backend, brief, text)
    response = langflow.post(
        f"/api/v1/run/{FLOW}",
        json={"input_value": json.dumps({"posting_id": posting_id}), "input_type": "chat", "output_type": "chat"},
    )
    assert response.status_code == 200, response.text[:800]
    detail = backend.get(f"/postings/{posting_id}")
    detail.raise_for_status()
    return posting_id, detail.json()


def artifact_text(backend: httpx.Client, posting_id: int, artifact: dict) -> str:
    response = backend.get(f"/postings/{posting_id}/artifacts/{artifact['kind']}")
    response.raise_for_status()
    return response.json()["markdown"]


@pytest.fixture(scope="module")
def english(backend: httpx.Client, langflow: httpx.Client) -> tuple[int, dict]:
    return generate(backend, langflow, EN_BRIEF, "Synthetic English posting for a platform engineer role.")


@pytest.fixture(scope="module")
def danish(backend: httpx.Client, langflow: httpx.Client) -> tuple[int, dict]:
    return generate(backend, langflow, DA_BRIEF, "Syntetisk dansk stillingsopslag til en dataingeniør.")


def test_matched_posting_gets_all_documents(english: tuple[int, dict]) -> None:
    _, detail = english
    assert detail["status"] == "generated"
    by_kind = {a["kind"]: a for a in detail["artifacts"]}
    assert set(by_kind) == {"cv", "cover_letter", "recruiter_email"}
    assert all(by_kind[k]["md_path"].endswith("_v1.md") for k in by_kind)
    assert by_kind["cv"]["pdf_path"] and by_kind["cover_letter"]["pdf_path"]
    assert by_kind["recruiter_email"]["pdf_path"] is None
    folder = Path(detail["host_folder"]) if detail["host_folder"] else None
    if folder and folder.is_dir():  # the test may run where the app folder is not visible
        names = {p.name for p in folder.iterdir()}
        assert {"cv_v1.md", "cv_v1.pdf", "cover_letter_v1.md", "cover_letter_v1.pdf", "recruiter_email_v1.md"} <= names


def test_documents_use_the_recruiter_name_and_have_no_placeholders(
    backend: httpx.Client, english: tuple[int, dict]
) -> None:
    posting_id, detail = english
    texts = {a["kind"]: artifact_text(backend, posting_id, a) for a in detail["artifacts"]}
    for kind, text in texts.items():
        assert "{{" not in text and "}}" not in text and "<!--" not in text, kind
    assert texts["recruiter_email"].startswith("Subject: Application for LLM Platform Engineer at ")
    assert "Maja" in texts["recruiter_email"]
    assert "Max Brumer" in texts["cover_letter"]
    cv = (PROFILE / "cv.md").read_text(encoding="utf-8")
    for heading in (line for line in cv.splitlines() if line.startswith("### ")):
        assert heading in texts["cv"]


def test_danish_posting_gives_english_documents(backend: httpx.Client, danish: tuple[int, dict]) -> None:
    posting_id, detail = danish
    assert detail["status"] == "generated"
    for artifact in detail["artifacts"]:
        text = artifact_text(backend, posting_id, artifact)
        assert "{{" not in text and "}}" not in text, artifact['kind']
        assert len(DANISH_WORDS.findall(text)) <= 3, artifact['kind']
    email = next(a for a in detail["artifacts"] if a["kind"] == "recruiter_email")
    assert "Hiring Team" in artifact_text(backend, posting_id, email)


def test_generation_is_a_noop_for_other_statuses(backend: httpx.Client, langflow: httpx.Client, english) -> None:
    posting_id, _ = english
    response = langflow.post(
        f"/api/v1/run/{FLOW}",
        json={"input_value": json.dumps({"posting_id": posting_id}), "input_type": "chat", "output_type": "chat"},
    )
    assert response.status_code == 200 and "nothing to generate" in response.text
    assert len(backend.get(f"/postings/{posting_id}").json()["artifacts"]) == 3


def test_fact_check_flags_a_planted_fake_skill() -> None:
    """Calls the same prompt, schema and model settings as AJS Fact Check on a doctored letter."""
    from test_generate_documents_static import load

    fact_check = load("ajs_fact_check")
    prompt = re.sub(r"\A---\n.*?\n---\n", "", (REPO / "langflow/prompts/fact_check.md").read_text(encoding="utf-8"), flags=re.S)
    cv = (PROFILE / "cv.md").read_text(encoding="utf-8")
    letter = (
        "Dear Hiring Team,\n\nAt IBM I lead a team of data engineers and shipped agentic AI workflows to production. "
        "Before that I spent six years as a Kubernetes platform architect at Google, where I managed a Rust "
        "compiler team and earned a PhD in physics from MIT.\n\nTake care,\nMax Brumer"
    )
    body = {
        "model": dotenv("LLM_AGENT_MODEL") or "ajs-gemma",
        "messages": [
            {"role": "system", "content": prompt.strip()},
            {"role": "user", "content": f"CV (the only source of truth about the candidate)\n{cv}\n\n=== DOCUMENT: cover_letter ===\n{letter}"},
        ],
        "stream": False,
        "think": False,
        "format": fact_check.SCHEMA,
        "options": {"temperature": 0.2, "num_predict": 2000},
    }
    response = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=600)
    response.raise_for_status()
    claims = json.loads(response.json()["message"]["content"])["claims"]
    flagged = " ".join(c["claim"].lower() for c in claims)
    assert any(word in flagged for word in ("kubernetes", "google", "rust", "mit", "phd")), claims
    assert "agentic" not in flagged, claims  # the supported claim is not flagged
