"""Static checks on the exported flows and prompts (no stack needed; runs in CI too)."""

import json
import re
import sys
from pathlib import Path

import pytest

LANGFLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LANGFLOW / "tools"))
from normalize_flow import find_secrets  # noqa: E402

FLOWS = sorted((LANGFLOW / "flows").glob("*.json"))
ALLOWED_BUILTIN = {"ChatInput", "ChatOutput", "TextInput", "TextOutput", "OllamaModel", "OllamaEmbeddings"}
FOREIGN_PROVIDERS = re.compile(
    r"openai|anthropic|cohere|mistral|google|gemini|azure|bedrock|amazon|groq|huggingface|watsonx|vertex",
    re.IGNORECASE,
)


def nodes(flow: dict) -> list[dict]:
    return flow["data"]["nodes"]


def template(node: dict) -> dict:
    return node["data"]["node"]["template"]


@pytest.fixture(params=FLOWS, ids=lambda p: p.stem)
def flow(request: pytest.FixtureRequest) -> dict:
    return json.loads(request.param.read_text(encoding="utf-8"))


def test_there_are_flows() -> None:
    assert (LANGFLOW / "flows" / "analyze_and_match.json").is_file()


def test_only_ollama_models(flow: dict) -> None:
    """Plan 08: no non-Ollama model component in any flow JSON."""
    for node in nodes(flow):
        kind = node["data"]["type"]
        assert kind in ALLOWED_BUILTIN or kind.startswith("Ajs"), f"unexpected component {kind}"
        assert not FOREIGN_PROVIDERS.search(kind), kind
        assert not any(f.get("_input_type") == "ModelInput" for f in template(node).values() if isinstance(f, dict))


def test_custom_components_do_not_import_other_providers() -> None:
    for path in (LANGFLOW / "components").rglob("*.py"):
        imports = [
            line for line in path.read_text(encoding="utf-8").splitlines() if re.match(r"\s*(import|from)\s", line)
        ]
        offenders = [line for line in imports if FOREIGN_PROVIDERS.search(line) and "lfx" not in line]
        assert not offenders, f"{path.name}: {offenders}"


def test_models_and_urls_come_from_global_variables(flow: dict) -> None:
    for node in nodes(flow):
        for name in ("model", "warm_model", "ollama_base_url", "embed_model", "keep_alive"):
            field = template(node).get(name)
            if field:
                assert field["load_from_db"] is True and re.fullmatch(r"[A-Z_]+", field["value"]), (node["id"], name)
        assert "num_ctx" not in template(node), "never override num_ctx per node"


def test_no_secrets_in_exported_json(flow: dict) -> None:
    assert find_secrets(flow) == []
    for node in nodes(flow):
        for name, field in template(node).items():
            if isinstance(field, dict) and name != "code":
                value = field.get("value")
                assert not (isinstance(value, str) and re.search(r"gemma|bge-m3", value, re.I)), (node["id"], name)


def prompt_body(path: Path) -> str:
    match = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, f"{path.name} lacks a version header"
    assert re.search(r"^version: \d+$", match.group(1), re.MULTILINE)
    return match.group(2).strip()


def test_prompts_mirror_the_flow() -> None:
    flow = json.loads((LANGFLOW / "flows" / "analyze_and_match.json").read_text(encoding="utf-8"))
    by_type = {n["data"]["type"]: template(n) for n in nodes(flow)}
    prompts = LANGFLOW / "prompts"
    assert by_type["AjsJobBrief"]["system_prompt"]["value"].strip() == prompt_body(prompts / "analyst_job_brief.md")
    assert by_type["AjsRubricScore"]["system_prompt"]["value"].strip() == prompt_body(prompts / "matcher_rubric.md")
    schema = (prompts / "schemas" / "job_brief.schema.json").read_text(encoding="utf-8")
    assert json.loads(by_type["AjsJobBrief"]["schema_json"]["value"]) == json.loads(schema)


def test_flow_code_matches_component_files(flow: dict) -> None:
    """The flow embeds each component's source; it must equal the file in langflow/components/ajs."""
    files = {p.stem: p.read_text(encoding="utf-8") for p in (LANGFLOW / "components" / "ajs").glob("*.py")}
    for node in nodes(flow):
        kind = node["data"]["type"]
        if kind.startswith("Ajs"):
            embedded = template(node)["code"]["value"]
            assert embedded in files.values(), (
                f"{kind}: embedded code differs from langflow/components/ajs (re-export?)"
            )
