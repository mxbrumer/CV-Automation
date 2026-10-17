"""scripts/governance_check.py must pass on the repo and fail on planted violations (plan 10)."""

import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("governance_check", REPO / "scripts" / "governance_check.py")
assert spec and spec.loader
gov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gov)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the parts of the repo the check reads."""
    shutil.copytree(REPO / "langflow" / "flows", tmp_path / "langflow" / "flows")
    shutil.copytree(REPO / "langflow" / "prompts", tmp_path / "langflow" / "prompts")
    (tmp_path / "backend").mkdir()
    return tmp_path


def planted_flow(tree: Path, kind: str = "OpenAIModel") -> Path:
    flow = json.loads((tree / "langflow" / "flows" / "analyze_and_match.json").read_text(encoding="utf-8"))
    node = copy.deepcopy(flow["data"]["nodes"][0])
    node["id"] = "planted"
    node["data"]["type"] = kind
    flow["data"]["nodes"].append(node)
    path = tree / "langflow" / "flows" / "planted.json"
    path.write_text(json.dumps(flow), encoding="utf-8")
    return path


def test_repo_passes() -> None:
    results = gov.run_all(REPO)
    assert {rule: problems for rule, problems in results.items() if problems} == {}


def test_planted_openai_component_fails(tree: Path) -> None:
    planted_flow(tree)
    problems = gov.check_flows(tree)
    assert any("planted" in p and "OpenAIModel" in p for p in problems)


def test_planted_base_url_fails(tree: Path) -> None:
    path = planted_flow(tree, "AjsJobBrief")
    flow = json.loads(path.read_text(encoding="utf-8"))
    template = flow["data"]["nodes"][-1]["data"]["node"]["template"]
    template["ollama_base_url"] = {"value": "https://api.example.com", "load_from_db": False}
    path.write_text(json.dumps(flow), encoding="utf-8")
    assert any("OLLAMA_BASE_URL" in p for p in gov.check_flows(tree))


def test_flow_code_importing_a_cloud_sdk_fails(tree: Path) -> None:
    path = planted_flow(tree, "AjsJobBrief")
    flow = json.loads(path.read_text(encoding="utf-8"))
    flow["data"]["nodes"][-1]["data"]["node"]["template"]["code"] = {"value": "import anthropic\n"}
    path.write_text(json.dumps(flow), encoding="utf-8")
    assert any("SDK" in p for p in gov.check_flows(tree))


@pytest.mark.parametrize("line", ["import openai", 'URL = "https://api.openai.com/v1"', "KEY = 'sk-" + "a" * 24 + "'"])
def test_cloud_sdk_strings_fail(tree: Path, line: str) -> None:
    (tree / "backend" / "client.py").write_text(line + "\n", encoding="utf-8")
    assert gov.check_sdk_strings(tree)


@pytest.mark.parametrize(
    "code",
    [
        'hook = egress_hook("fetcher")',
        "client = httpx.Client(base_url='https://example.com')",
    ],
)
def test_unpinned_http_client_fails(tree: Path, code: str) -> None:
    (tree / "backend" / "src").mkdir()
    (tree / "backend" / "src" / "client.py").write_text(code, encoding="utf-8")
    assert gov.check_egress(tree)


def test_pinned_http_client_passes(tree: Path) -> None:
    (tree / "backend" / "src").mkdir()
    code = 'c = httpx.Client(event_hooks={"request": [egress_hook("x", {"langflow"})]})'
    (tree / "backend" / "src" / "client.py").write_text(code, encoding="utf-8")
    assert gov.check_egress(tree) == []


def test_changed_prompt_fails(tree: Path) -> None:
    prompt = tree / "langflow" / "prompts" / "analyst_job_brief.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nExtra instruction.\n", encoding="utf-8")
    assert any("analyst_job_brief.md" in p for p in gov.check_prompts(tree))


def test_tracked_personal_files_fail() -> None:
    bad = ["backend/x.py", "profile/cv.md", "mail/offer.eml", "infra/.env", "docs/profile-examples/cv.example.md", "infra/.env.example", "frontend/.env.local.example", "frontend/.env.local"]
    problems = gov.check_tracked(bad)
    assert [p.split(":")[0] for p in problems] == [
        "profile/cv.md",
        "mail/offer.eml",
        "infra/.env",
        "frontend/.env.local",
    ]
