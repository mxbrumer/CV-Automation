"""Offline checks for the generation components and prompts (plan 09; no stack, runs in CI).

The components import `lfx`, which is only inside the LangFlow image, so a minimal stub stands in
for it. Only the pure helpers (budget guard, writer checks, evidence selection) are exercised.
"""

import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

LANGFLOW = Path(__file__).resolve().parents[1]
COMPONENTS = LANGFLOW / "components" / "ajs"
PROMPTS = LANGFLOW / "prompts"


def _install_lfx_stub() -> None:
    if "lfx" in sys.modules and not isinstance(sys.modules["lfx"], types.ModuleType):
        return
    names = {
        "lfx": {},
        "lfx.custom": {},
        "lfx.custom.custom_component": {},
        "lfx.custom.custom_component.component": {"Component": type("Component", (), {})},
        "lfx.io": {
            n: MagicMock()
            for n in (
                "DataInput",
                "DropdownInput",
                "IntInput",
                "MessageTextInput",
                "MultilineInput",
                "Output",
                "SecretStrInput",
                "StrInput",
            )
        },
        "lfx.schema": {},
        "lfx.schema.data": {"Data": MagicMock()},
        "lfx.schema.message": {"Message": MagicMock()},
    }
    for name, attrs in names.items():
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__dict__.update(attrs)
            sys.modules[name] = module


def load(name: str) -> types.ModuleType:
    _install_lfx_stub()
    spec = importlib.util.spec_from_file_location(f"ajs_test_{name}", COMPONENTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CV = """# Test Person

## Experience

### Acme — Data Engineer
*2020 – 2024*

- Built Airflow pipelines moving 2 TB per day.
- Mentored two analysts.

### Beta — Analyst
*2018 – 2020*

- Wrote SQL reports for finance.
"""


def posting(evidence_bullets: int = 3, cv: str = CV) -> dict:
    return {
        "job_brief": {"title": "Data Engineer", "must_have": ["Airflow"], "nice_to_have": ["dbt"], "keywords": ["etl"]},
        "cv_markdown": cv,
        "templates": {"cover_letter": "<!-- rules -->\nDear {{ x }}", "recruiter_email": "Dear {{ recruiter }}"},
        "evidence": [
            {"role": "Acme", "dates": "2020", "text": f"bullet {i} " + "x" * 80, "similarity": 1 - i / 1000}
            for i in range(evidence_bullets)
        ],
    }


LIMITS = {"num_ctx": 32768, "evidence": 8000, "template": 3000, "brief": 2000, "instructions": 2000, "output": 4000}


def test_budget_guard_leaves_a_small_prompt_alone() -> None:
    guard = load("ajs_budget_guard")
    data, log = guard.trim(posting(), LIMITS)
    assert log == [] and len(data["evidence"]) == 3


def test_budget_guard_trims_oversized_evidence_weakest_first() -> None:
    guard = load("ajs_budget_guard")
    big = posting(evidence_bullets=2000)  # ~2000 * 95 chars, far over the 8000-token budget
    data, log = guard.trim(big, LIMITS)
    kept = data["evidence"]
    assert 0 < len(kept) < 2000 and log
    assert guard.estimate_tokens(guard.evidence_text(kept)) <= LIMITS["evidence"]
    assert kept == big["evidence"][: len(kept)]  # the best-ranked bullets survive
    worst = data["budget"]["prompt_tokens_worst_case"]
    assert worst + LIMITS["output"] <= LIMITS["num_ctx"]


def test_budget_guard_strips_template_comments_when_a_template_is_oversized() -> None:
    guard = load("ajs_budget_guard")
    big = posting()
    big["templates"]["cover_letter"] = "<!--" + "rule " * 4000 + "-->\nDear {{ x }}"
    data, log = guard.trim(big, LIMITS)
    assert "<!--" not in data["templates"]["cover_letter"] and "cover_letter template comments removed" in log


def test_budget_guard_refuses_what_cannot_fit() -> None:
    guard = load("ajs_budget_guard")
    with pytest.raises(ValueError, match="does not fit num_ctx"):
        guard.trim(posting(cv="word " * 40000), LIMITS)


def test_writer_checks() -> None:
    writer = load("ajs_doc_writer")
    assert writer.problems("recruiter_email", "Dear {{ recruiter }}", CV)
    assert writer.problems("cover_letter", "<!-- x --> short", CV)
    assert writer.problems("cv", "# Test Person\n\n### Acme — Data Engineer", CV)  # Beta dropped
    assert not writer.problems("cv", CV, CV)
    assert not writer.problems("recruiter_email", "Dear Hiring Team, " + "word " * 100, CV)
    assert writer.problems("recruiter_email", "word " * 171, CV)
    assert writer.clean("```markdown\n# Hi\n```") == "# Hi"
    assert writer.clean("<!-- gone -->\nText") == "Text"


def test_email_writer_gets_the_cover_letter() -> None:
    writer = load("ajs_doc_writer")
    data = posting() | {"title": "Data Engineer", "company": "Acme", "documents": {"cover_letter": "Dear Maja, LETTER"}}
    email = writer.user_message("recruiter_email", data, "18 October 2026")
    assert "COVER LETTER\nDear Maja, LETTER" in email
    assert email.index("COVER LETTER") < email.index("TEMPLATE")
    assert "COVER LETTER" not in writer.user_message("cover_letter", data, "18 October 2026")
    with pytest.raises(ValueError, match="needs the cover letter"):
        writer.user_message("recruiter_email", data | {"documents": {}}, "18 October 2026")


def test_budget_guard_counts_the_letter_when_the_cv_is_shorter() -> None:
    guard = load("ajs_budget_guard")
    data, _ = guard.trim(posting(cv="# Tiny"), LIMITS)
    assert data["budget"]["prompt_tokens_worst_case"] >= LIMITS["instructions"] + guard.LETTER_TOKENS


def test_evidence_parsing_and_picking() -> None:
    selector = load("ajs_evidence_selector")
    bullets = selector.parse_bullets(CV)
    assert [b["role"] for b in bullets] == ["Acme — Data Engineer"] * 2 + ["Beta — Analyst"]
    assert bullets[0]["dates"] == "2020 – 2024"
    sims = {"airflow": [0.9, 0.1, 0.2], "sql": [0.1, 0.2, 0.8]}
    assert selector.pick(sims, 3, 1) == [0, 2]
    assert selector.pick(sims, 3, 2) == [0, 2, 1]


def _prompt_body(name: str) -> str:
    match = re.match(r"---\n(.*?)\n---\n(.*)", (PROMPTS / f"{name}.md").read_text(encoding="utf-8"), re.DOTALL)
    assert match and re.search(r"^version: \d+$", match.group(1), re.MULTILINE), name
    return match.group(2).strip()


def test_generation_prompts_mirror_the_flow() -> None:
    path = LANGFLOW / "flows" / "generate_documents.json"
    if not path.is_file():
        pytest.skip("flow not exported yet")
    flow = json.loads(path.read_text(encoding="utf-8"))
    by_kind = {}
    for node in flow["data"]["nodes"]:
        template = node["data"]["node"]["template"]
        if node["data"]["type"] == "AjsDocWriter":
            by_kind[template["kind"]["value"]] = template["system_prompt"]["value"].strip()
        if node["data"]["type"] == "AjsFactCheck":
            assert template["system_prompt"]["value"].strip() == _prompt_body("fact_check")
    assert by_kind == {
        "cv": _prompt_body("writer_cv"),
        "cover_letter": _prompt_body("writer_letter"),
        "recruiter_email": _prompt_body("writer_email"),
    }


def test_writer_model_is_a_global_variable() -> None:
    source = (COMPONENTS / "ajs_doc_writer.py").read_text(encoding="utf-8")
    assert 'value="LLM_WRITER_MODEL"' in source and "ajs-gemma" not in source
