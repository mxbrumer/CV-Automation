"""Golden tests for the LangFlow flows (plan 08).

They run the real flow through LangFlow's API against the running stack (`scripts/dev.ps1 up`,
flows imported, native Ollama with ajs-gemma and bge-m3), so they are marked `llm` and excluded
from CI. They create postings with source `golden-test` in the app database; use
`scripts/dev.ps1 reset-db` to clear them.

Run (from the repo root):
    cd backend; uv run --with jsonschema pytest ../langflow/tests -m llm -c ../langflow/tests/pytest.ini

Settings come from the environment, else from infra/.env: BACKEND_API_KEY, LANGFLOW_API_KEY (a
temporary key is created through the superuser login when it is empty), LANGFLOW_SUPERUSER(_PASSWORD).
"""

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000/api/v1")
LANGFLOW_URL = os.environ.get("LANGFLOW_URL", "http://127.0.0.1:7860")
FLOW = os.environ.get("LANGFLOW_ANALYSIS_FLOW_ID") or "analyze_and_match"
RUN_TIMEOUT = 900.0


def dotenv(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    env_file = REPO / "infra" / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"\s*{name}\s*=\s*(.*?)\s*$", line)
            if m:
                return m.group(1).strip("\"'")
    return ""


@pytest.fixture(scope="session")
def backend() -> Iterator[httpx.Client]:
    key = dotenv("BACKEND_API_KEY")
    with httpx.Client(base_url=BACKEND_URL, headers={"X-API-Key": key}, timeout=60) as client:
        try:
            client.get("/stats").raise_for_status()
        except httpx.HTTPError as exc:
            pytest.skip(f"backend not reachable at {BACKEND_URL}: {exc}")
        yield client


@pytest.fixture(scope="session")
def langflow() -> Iterator[httpx.Client]:
    key = dotenv("LANGFLOW_API_KEY")
    with httpx.Client(base_url=LANGFLOW_URL, timeout=RUN_TIMEOUT) as client:
        key_id = None
        bearer: dict[str, str] = {}
        if not key:  # create a temporary key and delete it afterwards
            login = client.post(
                "/api/v1/login",
                data={"username": dotenv("LANGFLOW_SUPERUSER"), "password": dotenv("LANGFLOW_SUPERUSER_PASSWORD")},
            )
            login.raise_for_status()
            bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
            created = client.post("/api/v1/api_key/", json={"name": "ajs-golden-tests"}, headers=bearer)
            created.raise_for_status()
            key, key_id = created.json()["api_key"], created.json().get("id")
        client.headers["x-api-key"] = key
        try:
            yield client
        finally:
            if key_id:
                client.delete(f"/api/v1/api_key/{key_id}", headers=bearer)


@pytest.fixture(scope="session")
def threshold(backend: httpx.Client) -> float:
    return float(os.environ.get("MATCH_THRESHOLD") or dotenv("MATCH_THRESHOLD") or 55)


class Runner:
    def __init__(self, backend: httpx.Client, langflow: httpx.Client) -> None:
        self.backend, self.langflow = backend, langflow

    def create(self, fixture: str) -> tuple[int, str]:
        text = (FIXTURES / fixture).read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        created = self.backend.post(
            "/tools/postings",
            json={
                "company": f"Golden Test {fixture.split('.')[0]}",
                "title": title,
                "source": "golden-test",
                "source_job_id": uuid.uuid4().hex,
                "posting_text": text,
            },
        )
        created.raise_for_status()
        return created.json()["posting_id"], text

    def run(self, posting_id: int, text: str | None = None) -> dict:
        payload: dict = {"posting_id": posting_id}
        if text is not None:
            payload["posting_text"] = text
        response = self.langflow.post(
            f"/api/v1/run/{FLOW}",
            json={"input_value": json.dumps(payload), "input_type": "chat", "output_type": "chat"},
        )
        assert response.status_code == 200, response.text[:500]
        return response.json()

    def posting(self, posting_id: int) -> dict:
        response = self.backend.get(f"/postings/{posting_id}")
        response.raise_for_status()
        return response.json()

    def analyze(self, fixture: str) -> dict:
        posting_id, text = self.create(fixture)
        self.run(posting_id, text)
        return self.posting(posting_id)


@pytest.fixture(scope="session")
def runner(backend: httpx.Client, langflow: httpx.Client) -> Runner:
    return Runner(backend, langflow)


@pytest.fixture(scope="session")
def strong(runner: Runner) -> dict:
    return runner.analyze("en_strong_match.md")


@pytest.fixture(scope="session")
def danish(runner: Runner) -> dict:
    return runner.analyze("da_danish_required.md")
