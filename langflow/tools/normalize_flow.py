"""Normalize an exported LangFlow flow for git: drop volatile UI state, strip secrets, sort keys.

Usage: python normalize_flow.py <input.json> <output.json>   (standard library only)

Also importable: `normalize(flow: dict) -> dict` and `find_secrets(flow: dict) -> list[str]`.
"""

import json
import re
import sys
from pathlib import Path

KEEP_TOP = (
    "id", "name", "description", "icon", "icon_bg_color", "gradient", "is_component",
    "endpoint_name", "tags", "data", "mcp_enabled", "locked", "webhook",
)  # fmt: skip
DROP_NODE = ("selected", "dragging", "measured", "positionAbsolute", "width", "height", "resizing")
DROP_EDGE = ("selected", "animated")
SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY)")


def normalize(flow: dict) -> dict:
    out = {k: flow[k] for k in KEEP_TOP if k in flow}
    data = out.get("data") or {}
    data.pop("viewport", None)
    for node in data.get("nodes", []):
        for key in DROP_NODE:
            node.pop(key, None)
        template = (node.get("data", {}).get("node", {}) or {}).get("template", {}) or {}
        for field in template.values():
            if not isinstance(field, dict):
                continue
            # Variable names (load_from_db) are kept; literal secrets are not.
            if (field.get("password") or field.get("type") == "SecretStr") and not field.get("load_from_db"):
                field["value"] = ""
    for edge in data.get("edges", []):
        for key in DROP_EDGE:
            edge.pop(key, None)
    data["nodes"] = sorted(data.get("nodes", []), key=lambda n: n["id"])
    data["edges"] = sorted(data.get("edges", []), key=lambda e: e["id"])
    out["data"] = data
    return out


def find_secrets(flow: dict) -> list[str]:
    """Locations of values that look like secrets (used by the tests and before committing)."""
    found: list[str] = []
    for node in flow.get("data", {}).get("nodes", []):
        template = node.get("data", {}).get("node", {}).get("template", {})
        for name, field in template.items():
            if not isinstance(field, dict):
                continue
            value = field.get("value")
            if field.get("password") and value and not field.get("load_from_db"):
                found.append(f"{node['id']}.{name}: secret field has a value")
            elif isinstance(value, str) and name != "code" and SECRET_VALUE.search(value):
                found.append(f"{node['id']}.{name}: value looks like a secret")
    return found


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    flow = normalize(json.loads(src.read_text(encoding="utf-8")))
    problems = find_secrets(flow)
    if problems:
        sys.exit("refusing to write, possible secrets: " + "; ".join(problems))
    text = json.dumps(flow, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


if __name__ == "__main__":
    main()
