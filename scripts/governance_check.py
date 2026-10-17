#!/usr/bin/env python3
"""Governance checks (plan 10, docs/governance.md). Standard library only; run from anywhere.

    python scripts/governance_check.py [--root DIR]

Exit code 1 when a rule is broken. Rules:
  flows    every model component is Ollama-based and takes its base URL from OLLAMA_BASE_URL
  sdk      no cloud-LLM SDK or key strings in backend/, langflow/ or frontend/src
  prompts  every langflow/prompts/*.md body is embedded verbatim in a flow
  tracked  no profile data, .eml or .env file is tracked by git
  egress   every httpx client in backend/src gets event hooks, and every egress_hook call pins
           the client with only_hosts (plan 15: the backend never reaches the public web)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

# Built-in LangFlow components a flow may use. Custom components are named Ajs*.
ALLOWED_BUILTIN = {
    "ChatInput",
    "ChatOutput",
    "TextInput",
    "TextOutput",
    "OllamaModel",
    "OllamaEmbeddings",
}
PROVIDERS = (
    r"openai|anthropic|cohere|mistral|google|gemini|azure|bedrock|amazon|groq|huggingface"
    r"|watsonx|vertex|deepseek|perplexity|xai|nvidia|sambanova|openrouter"
)
FOREIGN_PROVIDER = re.compile(PROVIDERS, re.IGNORECASE)
# A provider SDK imported by a component embedded in a flow.
FOREIGN_IMPORT = re.compile(rf"^\s*(?:import|from)\s+(?:langchain_)?(?:{PROVIDERS})", re.I | re.M)
BASE_URL_FIELD = re.compile(r"(base_?url|endpoint|api_?base)", re.IGNORECASE)

SDK_PATTERNS = [
    re.compile(r"\bopenai\b", re.IGNORECASE),
    re.compile(r"\banthropic\b", re.IGNORECASE),
    re.compile(r"api\.openai\.com", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
]
SCAN_DIRS = ["backend", "langflow", "frontend/src"]
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".toml", ".yml", ".yaml", ".ps1", ".txt"}
SKIP_PARTS = {".venv", "node_modules", "__pycache__", "certs", "flows", ".pytest_cache", ".mypy_cache"}
SKIP_NAMES = {"uv.lock", "package-lock.json"}
# Files that name providers on purpose (they are the checks). Paths relative to the root.
SDK_ALLOWLIST = {
    "backend/src/ajs/services/egress.py",  # the runtime guard lists hosted-LLM domains to refuse
    "backend/tests/test_flow_observability.py",
    "langflow/tests/test_flows_static.py",
    "langflow/tests/test_governance_check.py",
}


def _node_template(node: dict) -> dict:
    return node["data"]["node"]["template"]


def check_flows(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted((root / "langflow" / "flows").glob("*.json")):
        rel = path.relative_to(root).as_posix()
        flow = json.loads(path.read_text(encoding="utf-8"))
        for node in flow["data"]["nodes"]:
            kind = node["data"]["type"]
            where = f"{rel}: node {node['id']} ({kind})"
            if not (kind in ALLOWED_BUILTIN or kind.startswith("Ajs")):
                problems.append(f"{where}: component is not on the Ollama-only allowlist")
            elif FOREIGN_PROVIDER.search(kind):
                problems.append(f"{where}: cloud provider component")
            template = _node_template(node)
            for name, field in template.items():
                if not isinstance(field, dict):
                    continue
                if field.get("_input_type") == "ModelInput":
                    problems.append(f"{where}: generic model selector '{name}'")
                value = field.get("value")
                if name == "code":
                    if isinstance(value, str) and FOREIGN_IMPORT.search(value):
                        problems.append(f"{where}: code imports a cloud-LLM SDK")
                elif BASE_URL_FIELD.search(name) and isinstance(value, str) and value:
                    if not (field.get("load_from_db") and value == "OLLAMA_BASE_URL"):
                        problems.append(f"{where}: '{name}' must be the OLLAMA_BASE_URL variable")
    return problems


def _scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel_parts = path.relative_to(root).parts
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if path.name in SKIP_NAMES or SKIP_PARTS & set(rel_parts):
                continue
            if path.relative_to(root).as_posix() in SDK_ALLOWLIST:
                continue
            files.append(path)
    return files


def check_sdk_strings(root: Path) -> list[str]:
    problems: list[str] = []
    for path in _scan_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in SDK_PATTERNS:
                if pattern.search(line):
                    rel = path.relative_to(root).as_posix()
                    problems.append(f"{rel}:{lineno}: matches /{pattern.pattern}/")
                    break
    return problems


def _prompt_body(path: Path) -> str | None:
    match = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(encoding="utf-8"), re.DOTALL)
    return match.group(2).strip() if match else None


def check_prompts(root: Path) -> list[str]:
    problems: list[str] = []
    embedded: set[str] = set()
    for path in (root / "langflow" / "flows").glob("*.json"):
        flow = json.loads(path.read_text(encoding="utf-8"))
        for node in flow["data"]["nodes"]:
            for name, field in _node_template(node).items():
                value = field.get("value") if isinstance(field, dict) else None
                if name != "code" and isinstance(value, str):
                    embedded.add(value.strip())
    for prompt in sorted((root / "langflow" / "prompts").glob("*.md")):
        body = _prompt_body(prompt)
        if body is None:
            problems.append(f"{prompt.name}: missing '---' version header")
        elif body not in embedded:
            problems.append(
                f"{prompt.name}: not embedded verbatim in any flow "
                "(rebuild the flow with its langflow/tools builder, or update the prompt file)"
            )
    return problems


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def check_tracked(files: list[str]) -> list[str]:
    problems: list[str] = []
    for name in files:
        parts = name.split("/")
        base = parts[-1]
        if base.lower().endswith(".eml"):
            problems.append(f"{name}: e-mail file is tracked")
        elif base == ".env" or (base.startswith(".env.") and not base.endswith(".example")):
            problems.append(f"{name}: env file is tracked")
        elif "profile" in parts[:-1] and not base.endswith(".example.md"):
            problems.append(f"{name}: profile data is tracked")
    return problems


HTTPX_CLIENTS = {"Client", "AsyncClient"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def check_egress(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted((root / "backend" / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name, keywords = _call_name(node), {k.arg for k in node.keywords}
            if name == "egress_hook" and len(node.args) < 2 and "only_hosts" not in keywords:
                problems.append(f"{rel}:{node.lineno}: egress_hook without only_hosts")
            elif (
                name in HTTPX_CLIENTS
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "httpx"
                and "event_hooks" not in keywords
            ):
                problems.append(f"{rel}:{node.lineno}: httpx.{name} without an egress_hook")
    return problems


def run_all(root: Path, files: list[str] | None = None) -> dict[str, list[str]]:
    if files is None:
        try:
            files = tracked_files(root)
        except (OSError, subprocess.CalledProcessError):
            files = []
            print("warning: git unavailable, skipping the tracked-files check", file=sys.stderr)
    return {
        "flows": check_flows(root),
        "sdk": check_sdk_strings(root),
        "prompts": check_prompts(root),
        "tracked": check_tracked(files),
        "egress": check_egress(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    results = run_all(args.root.resolve())
    failed = False
    for rule, problems in results.items():
        print(f"{'FAIL' if problems else 'ok  '} {rule}")
        for problem in problems:
            print(f"     {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
