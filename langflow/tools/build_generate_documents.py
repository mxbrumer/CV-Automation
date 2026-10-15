"""Build the `generate_documents` flow and upsert it into the running LangFlow.

Same approach as build_analyze_and_match.py (which supplies the helpers): the flow is generated
from the component files and the mirrored prompts in langflow/prompts/*.md, which are embedded
verbatim. LangFlow stays the source of truth; export with scripts/export-flows.ps1.

    python langflow/tools/build_generate_documents.py            # upsert into LangFlow
    python langflow/tools/build_generate_documents.py --out f.json   # only write the JSON
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_analyze_and_match import Builder, login, read_prompt, request  # noqa: E402

FLOW_NAME = "generate_documents"
FLOW_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "ajs/flows/generate_documents"))

DESCRIPTION = (
    "Brief steps 11-15. Input: JSON {posting_id} of a `matched` posting. Selects CV evidence "
    "(bge-m3), keeps every call inside num_ctx, writes the CV, cover letter and recruiter email "
    "in English (writer model), fact-checks them against cv.md and saves them through the backend "
    "(status generated). One run per posting."
)


def build_flow(catalog: dict) -> dict:
    b = Builder(catalog)
    no_store = {"should_store_message": False}

    def writer(kind: str, prompt: str) -> dict:
        return {"kind": kind, "system_prompt": read_prompt(prompt)}

    b.add("chat_in", "input_output", "ChatInput", 0, 300, no_store)
    b.add("load", "ajs", "AjsLoadGeneration", 400, 300)
    b.add("skipped_out", "input_output", "ChatOutput", 800, 650, no_store)
    b.add("evidence", "ajs", "AjsEvidenceSelector", 800, 300)
    b.add("guard", "ajs", "AjsBudgetGuard", 1200, 300)
    b.add("cv", "ajs", "AjsDocWriter", 1600, 300, writer("cv", "writer_cv"))
    b.add("letter", "ajs", "AjsDocWriter", 2000, 300, writer("cover_letter", "writer_letter"))
    b.add("email", "ajs", "AjsDocWriter", 2400, 300, writer("recruiter_email", "writer_email"))
    b.add("fact", "ajs", "AjsFactCheck", 2800, 300, {"system_prompt": read_prompt("fact_check")})
    b.add("save", "ajs", "AjsSaveGeneration", 3200, 300)
    b.add("result_out", "input_output", "ChatOutput", 3600, 300, no_store)

    b.connect("chat_in", "message", "load", "input_value")
    b.connect("load", "skipped", "skipped_out", "input_value")
    b.connect("load", "posting", "evidence", "posting")
    b.connect("evidence", "posting_out", "guard", "posting")
    b.connect("guard", "posting_out", "cv", "posting")
    b.connect("cv", "posting_out", "letter", "posting")
    b.connect("letter", "posting_out", "email", "posting")
    b.connect("email", "posting_out", "fact", "posting")
    b.connect("fact", "posting_out", "save", "posting")
    b.connect("save", "result", "result_out", "input_value")

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
    if args.out:
        Path(args.out).write_text(json.dumps(flow, indent=2), encoding="utf-8")
        return
    result = request("PUT", f"/api/v1/flows/{FLOW_ID}", token, json.dumps(flow).encode("utf-8"))
    print(f"upserted {result['name']} ({result['id']})")


if __name__ == "__main__":
    main()
