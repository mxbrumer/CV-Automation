#!/usr/bin/env python3
"""Upload the plan 08 golden postings to Phoenix as the dataset `ajs-golden-postings` (plan 10).

    python scripts/upload_golden_dataset.py [--url http://127.0.0.1:6006]

Inputs are the fixture postings in langflow/tests/fixtures; outputs are what
langflow/tests/test_analyze_and_match.py asserts. Re-running does nothing when the dataset
exists (it never duplicates examples). Experiments are recorded by hand, see
docs/model-evaluation.md.
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "langflow" / "tests" / "fixtures"
NAME = "ajs-golden-postings"
EXPECTED = {
    "en_strong_match.md": {
        "status": "awaiting_match_review",
        "language": "en",
        "danish_required": False,
        "recruiter_email": "freja.holm@nordlys-analytics.example",
    },
    "en_weak_match.md": {"status": "low_match", "language": "en"},
    "da_danish_required.md": {"language": "da", "danish_required": True},
    "de_unsupported.md": {"status": "unsupported_language"},
}


def call(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:6006")
    args = parser.parse_args()
    existing = {d["name"] for d in call(f"{args.url}/v1/datasets")["data"]}
    if NAME in existing:
        print(f"{NAME} already exists; nothing to do")
        return 0
    names = sorted(EXPECTED)
    body = {
        "action": "create",
        "name": NAME,
        "description": "Golden postings for analyze_and_match (plan 08 tests)",
        "inputs": [{"fixture": n, "posting_text": (FIXTURES / n).read_text(encoding="utf-8")} for n in names],
        "outputs": [EXPECTED[n] for n in names],
        "metadata": [{"source": "langflow/tests/fixtures"} for _ in names],
    }
    result = call(f"{args.url}/v1/datasets/upload?sync=true", body)
    print(f"uploaded {len(names)} examples to {NAME}: {result.get('data')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
