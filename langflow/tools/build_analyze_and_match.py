"""Build the `analyze_and_match` flow and upsert it into the running LangFlow.

LangFlow stays the source of truth once the flow exists (edit it in the UI, then run
scripts/export-flows.ps1). This script exists so the flow can be regenerated reproducibly from
the component files and the mirrored prompts (langflow/prompts/*.md), which it embeds verbatim.

    python langflow/tools/build_analyze_and_match.py            # upsert into LangFlow
    python langflow/tools/build_analyze_and_match.py --out f.json   # only write the JSON

Standard library only. Reads LANGFLOW_SUPERUSER(_PASSWORD) from infra/.env; nothing is printed.
"""

import argparse
import gzip
import json
import re
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "langflow" / "prompts"
FLOW_NAME = "analyze_and_match"
FLOW_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "ajs/flows/analyze_and_match"))
BASE = "http://127.0.0.1:7860"

DESCRIPTION = (
    "Brief steps 2-10. Input: JSON {posting_id, posting_text}. Detects language, extracts the "
    "job_brief and recruiter contact (Gemma), scores the CV match (bge-m3 + rubric) and saves "
    "everything through the backend tool endpoints. One run per posting; safe to retry."
)


def dotenv(name: str) -> str:
    for line in (REPO / "infra" / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{name}\s*=\s*(.*?)\s*$", line)
        if m:
            return m.group(1).strip("\"'")
    raise SystemExit(f"{name} missing in infra/.env")


def request(
    method: str, path: str, token: str | None = None, body: bytes | None = None, ctype: str = "application/json"
):
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Accept-Encoding", "identity")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if raw[:2] == bytes([0x1F, 0x8B]):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def login() -> str:
    form = urllib.parse.urlencode(
        {"username": dotenv("LANGFLOW_SUPERUSER"), "password": dotenv("LANGFLOW_SUPERUSER_PASSWORD")}
    ).encode()
    return request("POST", "/api/v1/login", body=form, ctype="application/x-www-form-urlencoded")["access_token"]


def read_prompt(name: str) -> str:
    """Body of langflow/prompts/<name>.md without the version header."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n.*?\n---\n(.*)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"{name}.md has no version header")
    return match.group(1).strip()


def handle(obj: dict, spaced: bool) -> str:
    text = json.dumps(obj, separators=(", ", ": ") if spaced else (",", ":"))
    return text.replace('"', "œ")


class Builder:
    def __init__(self, catalog: dict) -> None:
        self.catalog = catalog
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.by_key: dict[str, dict] = {}

    def component(self, category: str, key: str) -> dict:
        found = self.catalog[category]
        match = found.get(key) or next(v for k, v in found.items() if k.split(":")[-1].split("@")[0] == key)
        return json.loads(json.dumps(match))  # deep copy

    def add(self, alias: str, category: str, key: str, x: int, y: int, values: dict | None = None) -> None:
        node_def = self.component(category, key)
        component_name = node_def["name"] if "name" in node_def else key
        for field, value in (values or {}).items():
            node_def["template"][field]["value"] = value
        node_id = f"{component_name}-{alias}"
        self.nodes.append(
            {
                "id": node_id,
                "type": "genericNode",
                "position": {"x": x, "y": y},
                "data": {
                    "id": node_id,
                    "type": component_name,
                    "display_name": node_def.get("display_name"),
                    "description": node_def.get("description"),
                    "node": node_def,
                    "showNode": True,
                },
            }
        )
        self.by_key[alias] = {"id": node_id, "type": component_name, "def": node_def}

    def connect(self, src: str, output: str, dst: str, field: str) -> None:
        s, d = self.by_key[src], self.by_key[dst]
        out_def = next(o for o in s["def"]["outputs"] if o["name"] == output)
        field_def = d["def"]["template"][field]
        source_handle = {
            "dataType": s["type"],
            "id": s["id"],
            "name": output,
            "output_types": out_def["types"],
        }
        target_handle = {
            "fieldName": field,
            "id": d["id"],
            "inputTypes": field_def.get("input_types") or [],
            "type": field_def.get("type", "other"),
        }
        edge_id = f"reactflow__edge-{s['id']}{handle(source_handle, False)}-{d['id']}{handle(target_handle, False)}"
        self.edges.append(
            {
                "id": edge_id,
                "source": s["id"],
                "target": d["id"],
                "sourceHandle": handle(source_handle, True),
                "targetHandle": handle(target_handle, True),
                "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
                "className": "",
            }
        )


def build_flow(catalog: dict) -> dict:
    b = Builder(catalog)
    no_store = {"should_store_message": False}
    brief_values = {
        "system_prompt": read_prompt("analyst_job_brief"),
        "schema_json": (PROMPTS / "schemas" / "job_brief.schema.json").read_text(encoding="utf-8").strip(),
    }
    b.add("chat_in", "input_output", "ChatInput", 0, 300, no_store)
    b.add("load", "ajs", "AjsLoadPosting", 400, 300)
    b.add("skipped_out", "input_output", "ChatOutput", 800, 650, no_store)
    b.add("language", "ajs", "AjsDetectLanguage", 800, 300)
    b.add("unsupported", "ajs", "AjsSetStatus", 1200, 0, {"to": "unsupported_language"})
    b.add("unsupported_out", "input_output", "ChatOutput", 1600, 0, no_store)
    b.add("contacts", "ajs", "AjsExtractContacts", 1200, 300)
    b.add("brief", "ajs", "AjsJobBrief", 1600, 300, brief_values)
    b.add("save_analysis", "ajs", "AjsSaveAnalysis", 2000, 300)
    b.add("embedding", "ajs", "AjsEmbeddingScore", 2400, 300)
    b.add("rubric", "ajs", "AjsRubricScore", 2800, 300, {"system_prompt": read_prompt("matcher_rubric")})
    b.add("save_match", "ajs", "AjsSaveMatch", 3200, 300)
    b.add("result_out", "input_output", "ChatOutput", 3600, 300, no_store)

    b.connect("chat_in", "message", "load", "input_value")
    b.connect("load", "posting", "language", "posting")
    b.connect("load", "skipped", "skipped_out", "input_value")
    b.connect("language", "unsupported", "unsupported", "posting")
    b.connect("unsupported", "result", "unsupported_out", "input_value")
    b.connect("language", "supported", "contacts", "posting")
    b.connect("contacts", "posting_out", "brief", "posting")
    b.connect("brief", "posting_out", "save_analysis", "posting")
    b.connect("save_analysis", "posting_out", "embedding", "posting")
    b.connect("embedding", "posting_out", "rubric", "posting")
    b.connect("rubric", "posting_out", "save_match", "posting")
    b.connect("save_match", "result", "result_out", "input_value")

    return {
        "id": FLOW_ID,
        "name": FLOW_NAME,
        "description": DESCRIPTION,
        "endpoint_name": FLOW_NAME,
        "icon": "Workflow",
        "tags": ["ajs"],
        "is_component": False,
        "data": {"nodes": b.nodes, "edges": b.edges, "viewport": {"x": 0, "y": 0, "zoom": 0.5}},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the flow JSON here instead of upserting into LangFlow")
    args = parser.parse_args()
    token = login()
    flow = build_flow(request("GET", "/api/v1/all", token))
    body = json.dumps(flow).encode("utf-8")
    if args.out:
        Path(args.out).write_text(json.dumps(flow, indent=2), encoding="utf-8")
        return
    result = request("PUT", f"/api/v1/flows/{FLOW_ID}", token, body)
    print(f"upserted {result['name']} ({result['id']})")


if __name__ == "__main__":
    main()
