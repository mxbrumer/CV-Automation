# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "jsonschema>=4.23"]
# ///
"""Plan 04 model benchmark for ajs-gemma (the baseline configs stay available via --models mimir,qwen).

Calls the Ollama HTTP API directly. Inputs are real postings in
DATA_ROOT/profile/eval_postings/*.md (or .txt) with an optional labels.json:

    {"DA-posting-1.md": {"company": "...", "title": "...", "language": "da", "has_contact": true,
                          "location": "Aarhus", "danish_required": false}}   (the last two are optional)

Outputs go to DATA_ROOT/evals/ and are never committed:
    <date>[-tag].md             report
    <date>[-tag]-raw.jsonl      one line per model call
    <date>[-tag]-ratings.csv    blind cover letters and recruiter emails; fill in the `rating` column (1-5)
    <date>[-tag]-key.json       row id -> model (do not open before rating)

Usage (from the repo root):
    uv run backend/evals/model_bench.py run [--tag t1] [--models ajs-gemma] [--repeats 3]
    uv run backend/evals/model_bench.py score C:/dev/JobSearchData/evals/<date>-ratings.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator

DATA_ROOT = Path(os.environ.get("DATA_ROOT", r"C:\dev\JobSearchData"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
KEEP_ALIVE = "30m"
AGENT_TEMPERATURE = 0.2
WRITER_TEMPERATURE = 0.7
# Output cap for thinking calls. Gemma 4 can loop in its reasoning until num_ctx is full (30k tokens,
# 8 min in the first run). Successful calls use at most ~1700 tokens. A call that hits the cap is retried
# once with thinking off (plan 04 decision); both attempts are recorded in `detail`.
THINK_MAX_TOKENS = 3072
# Output caps for the other calls. Without them a model can generate until the HTTP timeout
# (Mimir looped on schema-constrained JSON with context shifting in the first run).
TOOL_MAX_TOKENS = 512
JSON_MAX_TOKENS = 2048
# Writing checks (plan 04): no placeholder left, and a word range.
LETTER_WORDS = (150, 450)
EMAIL_MAX_WORDS = 150


@dataclass(frozen=True)
class ModelCfg:
    alias: str
    name: str
    num_ctx: int
    thinking: bool  # accepts the `think` request option


def model_table(num_ctx: int) -> dict[str, ModelCfg]:
    return {
        "ajs-gemma": ModelCfg("ajs-gemma", os.environ.get("LLM_AGENT_MODEL", "ajs-gemma"), num_ctx, True),
        "mimir": ModelCfg("mimir", "hf.co/danish-foundation-models/DFM-Mimir-GGUF:Q4_K_M", 4096, False),
        "qwen": ModelCfg("qwen", "qwen2.5:14b", 8192, False),
    }


# Tasks each model takes part in (plan 04 step 4).
TASKS_BY_MODEL = {
    "ajs-gemma": ("tool", "extract", "rubric", "letter", "email"),
    "mimir": ("tool", "extract", "letter"),
    "qwen": ("tool", "extract"),
}

FIND_APPLICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "find_application",
        "description": "Check whether an application for this job already exists. Call it before creating an application.",
        "parameters": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Hiring company name as written in the posting"},
                "title": {"type": "string", "description": "Job title as written in the posting"},
            },
            "required": ["company", "title"],
        },
    },
}

NULLABLE_STR = {"type": ["string", "null"]}
JOB_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "company",
        "language",
        "contact",
        "must_have",
        "nice_to_have",
        "keywords",
        "location",
        "relocation_ok",
        "required_languages",
        "danish_required",
        "company_values",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "company": {"type": "string", "minLength": 1},
        "language": {"enum": ["da", "en"]},
        "contact": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {"name": NULLABLE_STR, "email": NULLABLE_STR, "phone": NULLABLE_STR},
        },
        "must_have": {"type": "array", "items": {"type": "string"}},
        "nice_to_have": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 25},
        "location": NULLABLE_STR,
        "relocation_ok": {"type": ["boolean", "null"]},
        "required_languages": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "danish_required": {"type": "boolean"},
        "company_values": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}

# D10: location and language are flags in job_brief, not scored.
RUBRIC_CRITERIA = ("skills", "experience", "domain")
RUBRIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scores", "rationale"],
    "properties": {
        "scores": {
            "type": "object",
            "required": list(RUBRIC_CRITERIA),
            "properties": {c: {"type": "integer", "minimum": 0, "maximum": 5} for c in RUBRIC_CRITERIA},
        },
        "rationale": {"type": "string"},
    },
}

# Used when DATA_ROOT/profile/cv.md does not exist. Fictional; no personal data.
FICTIONAL_PROFILE = """\
Candidate profile (fictional benchmark candidate)
- 7 years as a data engineer, the last 3 as senior/lead, at a European logistics company and a SaaS scale-up.
- Python, SQL, dbt, Airflow, Spark/Databricks, Azure (Data Factory, Synapse), some Microsoft Fabric, Terraform, Docker.
- Built a lakehouse on Databricks serving 40 analysts; cut nightly pipeline runtime from 5 h to 50 min.
- Shipped two LLM features to production (RAG search over support tickets, document classification); MLflow.
- Mentors junior engineers; works directly with business stakeholders on requirements.
- MSc Computer Science. English fluent; Danish intermediate (B1), actively studying.
- Relocating to Aarhus, Denmark; open to hybrid work anywhere in Jutland or Copenhagen.
"""


@dataclass
class Call:
    model: str
    task: str
    posting: str
    ok: bool
    wall_s: float
    prompt_tokens: int = 0
    eval_tokens: int = 0
    prompt_s: float = 0.0
    eval_s: float = 0.0
    load_s: float = 0.0
    think: bool | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class Ollama:
    def __init__(self, url: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=httpx.Timeout(900.0, connect=10.0))

    def version(self) -> str:
        return str(self.http.get("/api/version").json().get("version", "?"))

    def ps(self) -> list[dict[str, Any]]:
        return list(self.http.get("/api/ps").json().get("models", []))

    def unload_all(self) -> None:
        for m in self.ps():
            self.http.post("/api/generate", json={"model": m["name"], "keep_alive": 0})
        for _ in range(60):
            if not self.ps():
                break
            time.sleep(1)
        time.sleep(2)  # the driver frees VRAM slightly after the runner exits

    def embed(self, text: str) -> None:
        # A fresh runner can fail CUDA init when VRAM is tight; the retry count is reported.
        for attempt in range(3):
            r = self.http.post("/api/embed", json={"model": EMBED_MODEL, "input": text, "keep_alive": KEEP_ALIVE})
            if r.status_code == 200:
                return
            if attempt == 2:
                r.raise_for_status()
            time.sleep(2)

    def chat(
        self,
        cfg: ModelCfg,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        tools: list[dict[str, Any]] | None = None,
        fmt: str | dict[str, Any] | None = None,
        think: bool | None = None,
        num_predict: int | None = None,
    ) -> tuple[dict[str, Any], float]:
        options: dict[str, Any] = {"temperature": temperature, "num_ctx": cfg.num_ctx}
        if num_predict:
            options["num_predict"] = num_predict
        body: dict[str, Any] = {
            "model": cfg.name,
            "messages": messages,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": options,
        }
        if tools:
            body["tools"] = tools
        if fmt:
            body["format"] = fmt
        if cfg.thinking:
            # Gemma 4 thinks by default; every call states it explicitly.
            body["think"] = bool(think)
        t0 = time.perf_counter()
        r = self.http.post("/api/chat", json=body)
        wall = time.perf_counter() - t0
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json(), wall


def timing(resp: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_tokens": int(resp.get("prompt_eval_count", 0)),
        "eval_tokens": int(resp.get("eval_count", 0)),
        "prompt_s": resp.get("prompt_eval_duration", 0) / 1e9,
        "eval_s": resp.get("eval_duration", 0) / 1e9,
        "load_s": resp.get("load_duration", 0) / 1e9,
    }


def norm(s: str) -> str:
    s = s.casefold()
    s = re.sub(r"\b(a/s|aps|as|inc|ltd|gmbh)\b", " ", s)
    return re.sub(r"[^\wæøå]+", " ", s).strip()


def name_match(got: str, want: str) -> bool:
    g, w = norm(got), norm(want)
    return bool(g) and (g == w or w in g or g in w)


def title_match(got: str, want: str) -> bool:
    if name_match(got, want):
        return True
    g, w = set(norm(got).split()), set(norm(want).split())
    return bool(g and w) and len(g & w) / len(g | w) >= 0.5


def parse_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text)


# --- tasks -------------------------------------------------------------------


def task_tool(o: Ollama, cfg: ModelCfg, name: str, text: str, label: dict[str, Any]) -> Call:
    messages = [
        {
            "role": "system",
            "content": "You are the intake agent of a job-application assistant. Before an application is created you "
            "must check for duplicates by calling the find_application tool with the hiring company and the job "
            "title exactly as written in the posting. Do not answer in text.",
        },
        {"role": "user", "content": f"Job posting:\n\n{text}"},
    ]
    resp, wall = o.chat(
        cfg, messages, temperature=AGENT_TEMPERATURE, tools=[FIND_APPLICATION_TOOL], think=False, num_predict=TOOL_MAX_TOKENS
    )
    calls = resp.get("message", {}).get("tool_calls") or []
    args: dict[str, Any] = {}
    named = False
    for c in calls:
        fn = c.get("function", {})
        if fn.get("name") == "find_application":
            named = True
            args = fn.get("arguments") or {}
            break
    company, title = str(args.get("company", "")), str(args.get("title", ""))
    ok = named and bool(company) and bool(title)
    if ok and label:
        ok = name_match(company, label["company"]) and title_match(title, label["title"])
    detail = {"called": named, "args": args, "n_calls": len(calls), "content": resp["message"].get("content", "")[:200]}
    return Call(cfg.alias, "tool", name, ok, wall, detail=detail, **timing(resp))


def json_format(mode: str, schema: dict[str, Any]) -> str | dict[str, Any] | None:
    # `schema` is the default: with Ollama 0.34.4, format="json" plus think=false makes
    # Gemma 4 emit broken JSON (see docs/model-evaluation.md).
    return {"schema": schema, "json": "json", "none": None}[mode]


def task_extract(o: Ollama, cfg: ModelCfg, name: str, text: str, label: dict[str, Any], mode: str) -> Call:
    messages = [
        {
            "role": "system",
            "content": "Extract a job brief from the posting. Reply with one JSON object and nothing else, matching this "
            f"JSON schema:\n{json.dumps(JOB_BRIEF_SCHEMA)}\n"
            "Rules: language is the posting language as an ISO 639-1 code (da or en). contact is the named recruiter "
            "or contact person with name, email and phone (null for unknown fields), or null if nobody is named. "
            "location is the work location as written (city or region), or null. relocation_ok is true if the posting "
            "offers relocation support or accepts candidates who still have to move, false if it requires living "
            "locally already, null if not stated. required_languages lists the ISO 639-1 codes of languages the "
            "posting requires (not 'nice to have'). danish_required is true only if Danish is required. "
            "company_values lists values, principles or ways of working the posting itself states about the company "
            "(at most 3 short phrases of up to 4 words, in English); use [] if it states none. Never invent values. "
            "List items are short (at most 12 words) and in the posting's language. At most 25 keywords.",
        },
        {"role": "user", "content": text},
    ]
    resp, wall = o.chat(
        cfg,
        messages,
        temperature=AGENT_TEMPERATURE,
        fmt=json_format(mode, JOB_BRIEF_SCHEMA),
        think=False,
        num_predict=JSON_MAX_TOKENS,
    )
    content = resp.get("message", {}).get("content", "")
    detail: dict[str, Any] = {"done_reason": resp.get("done_reason")}
    try:
        data = parse_json(content)
        errors = [e.message for e in Draft202012Validator(JOB_BRIEF_SCHEMA).iter_errors(data)]
    except (json.JSONDecodeError, TypeError) as e:
        data, errors = None, [f"invalid JSON: {e}"]
    valid = not errors
    detail["schema_errors"] = errors[:5]
    if isinstance(data, dict) and label:
        contact = data.get("contact")
        has_contact = isinstance(contact, dict) and any(contact.get(k) for k in ("name", "email", "phone"))
        detail["fields"] = {
            "language": data.get("language") == label["language"],
            "company": name_match(str(data.get("company", "")), label["company"]),
            "title": title_match(str(data.get("title", "")), label["title"]),
            "contact": has_contact == label["has_contact"],
        }
        if "danish_required" in label:
            detail["fields"]["danish_required"] = data.get("danish_required") == label["danish_required"]
        if label.get("location"):
            detail["fields"]["location"] = name_match(str(data.get("location") or ""), label["location"])
    return Call(cfg.alias, "extract", name, valid, wall, detail=detail, **timing(resp))


def task_rubric(o: Ollama, cfg: ModelCfg, name: str, text: str, profile: str, think: bool, mode: str, temperature: float) -> Call:
    messages = [
        {
            "role": "system",
            "content": "You score how well a candidate matches a job posting. Score each criterion from 0 (no match) "
            "to 5 (perfect match): skills (required technical skills), experience (seniority and years), domain "
            "(industry and problem area). Do not score location or spoken languages; they are handled separately. "
            "Be strict: 3 means a partial match. Reply with one JSON object and nothing else: "
            '{"scores": {"skills": int, "experience": int, "domain": int}, '
            '"rationale": "at most 60 words"}',
        },
        {"role": "user", "content": f"CANDIDATE\n{profile}\n\nJOB POSTING\n{text}"},
    ]
    def attempt(th: bool) -> tuple[dict[str, Any], float]:
        return o.chat(
            cfg,
            messages,
            temperature=temperature,
            fmt=json_format(mode, RUBRIC_SCHEMA),
            think=th,
            num_predict=THINK_MAX_TOKENS if th else JSON_MAX_TOKENS,
        )

    resp, wall = attempt(think)
    fallback: dict[str, Any] = {}
    if think and resp.get("done_reason") == "length":
        fallback = {"capped_wall_s": round(wall, 1), "capped_eval_tokens": int(resp.get("eval_count", 0))}
        resp, wall2 = attempt(False)
        wall += wall2
    content = resp.get("message", {}).get("content", "")
    thinking = resp.get("message", {}).get("thinking") or ""
    detail: dict[str, Any] = {
        "temperature": temperature,
        "thinking_chars": len(thinking),
        "done_reason": resp.get("done_reason"),
        "fallback_think_off": bool(fallback),
        **fallback,
    }
    if not content.strip():
        detail["thinking_tail"] = thinking[-400:]
    try:
        data = parse_json(content)
        errors = [e.message for e in Draft202012Validator(RUBRIC_SCHEMA).iter_errors(data)]
    except (json.JSONDecodeError, TypeError) as e:
        data, errors = None, [f"invalid JSON: {e}"]
    if not errors and isinstance(data, dict):
        scores = {c: int(data["scores"][c]) for c in RUBRIC_CRITERIA}
        detail["scores"] = scores
        detail["total"] = round(sum(scores.values()) / (5 * len(RUBRIC_CRITERIA)) * 100)
    detail["schema_errors"] = errors[:5]
    return Call(cfg.alias, "rubric", name, not errors, wall, think=think, detail=detail, **timing(resp))


def read_template(name: str) -> str:
    text = (DATA_ROOT / "profile" / name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.DOTALL).strip()


def extract_brief(o: Ollama, cfg: ModelCfg, text: str) -> dict[str, Any] | None:
    """Job brief that feeds the writing tasks (same schema as task_extract)."""
    messages = [
        {
            "role": "system",
            "content": "Extract a job brief from the posting. Reply with one JSON object and nothing else, matching this "
            f"JSON schema:\n{json.dumps(JOB_BRIEF_SCHEMA)}\nList items are short and in the posting's language, except "
            "company_values (English). company_values holds only values the posting itself states about the company; "
            "use [] if it states none. Never invent values.",
        },
        {"role": "user", "content": text},
    ]
    # Retry at a higher temperature: at 0.2 some postings end in truncated JSON or a server "token repeat limit" error.
    for temperature in (AGENT_TEMPERATURE, 0.5, 0.8):
        try:
            resp, _ = o.chat(cfg, messages, temperature=temperature, fmt=JOB_BRIEF_SCHEMA, think=False, num_predict=JSON_MAX_TOKENS)
            data = parse_json(resp.get("message", {}).get("content", ""))
            if isinstance(data, dict) and not list(Draft202012Validator(JOB_BRIEF_SCHEMA).iter_errors(data)):
                return data
        except (RuntimeError, json.JSONDecodeError, TypeError):
            continue
    return None


WRITER_RULES = (
    "Fill the template. Each {{ ... }} is an instruction: replace it with text that follows the instruction, using only "
    "facts from the job brief, the posting or the candidate CV. Keep every sentence outside {{ }} exactly as written. "
    "Write English only. Never claim a skill, employer, date or degree that is not in the CV. Output only the finished "
    "text: no commentary, no code fences, no remaining {{ }} and no placeholders. Write job titles in English. "
    "For 'values' placeholders use only job_brief.company_values. If it is empty, do not mention diversity, inclusion "
    "or other generic values: describe the company's stated mission or domain instead (for example 'building secure "
    "banking technology'), taken from the posting."
)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def writer_messages(system: str, template: str, brief: dict[str, Any] | None, text: str, profile: str) -> list[dict[str, str]]:
    brief_json = json.dumps(brief, ensure_ascii=False) if brief else "(none)"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"TEMPLATE\n{template}\n\nJOB BRIEF\n{brief_json}\n\nJOB POSTING\n{text}\n\nCANDIDATE CV\n{profile}",
        },
    ]


def task_letter(o: Ollama, cfg: ModelCfg, name: str, text: str, profile: str, brief: dict[str, Any] | None) -> Call:
    today = datetime.now().astimezone().strftime("%d %B %Y").lstrip("0")
    messages = writer_messages(
        WRITER_RULES + f" Today's date is {today}.", read_template("cover_letter_template.md"), brief, text, profile
    )
    resp, wall = o.chat(cfg, messages, temperature=WRITER_TEMPERATURE, think=False, num_predict=1500)
    content = (resp.get("message", {}).get("content") or "").strip()
    words = word_count(content)
    unresolved = "{{" in content or "}}" in content
    ok = bool(content) and not unresolved and LETTER_WORDS[0] <= words <= LETTER_WORDS[1]
    detail = {"text": content, "kind": "letter", "words": words, "unresolved": unresolved}
    return Call(cfg.alias, "letter", name, ok, wall, detail=detail, **timing(resp))


def task_email(o: Ollama, cfg: ModelCfg, name: str, text: str, profile: str, brief: dict[str, Any] | None) -> Call:
    contact = (brief or {}).get("contact") or {}
    recruiter = contact.get("name") or "Hiring Team"
    messages = writer_messages(
        WRITER_RULES + f" The recruiter to greet is: {recruiter}.", read_template("recruiter_email_template.md"), brief, text, profile
    )
    resp, wall = o.chat(cfg, messages, temperature=WRITER_TEMPERATURE, think=False, num_predict=700)
    content = (resp.get("message", {}).get("content") or "").strip()
    words = word_count(content)
    unresolved = "{{" in content or "}}" in content
    ok = bool(content) and not unresolved and words <= EMAIL_MAX_WORDS
    detail = {"text": content, "kind": "email", "words": words, "unresolved": unresolved}
    return Call(cfg.alias, "email", name, ok, wall, detail=detail, **timing(resp))


# --- run ---------------------------------------------------------------------


def load_postings(folder: Path) -> tuple[list[tuple[str, str]], dict[str, dict[str, Any]]]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".md", ".txt"})
    if not files:
        sys.exit(f"No postings (*.md, *.txt) in {folder}")
    labels_path = folder / "labels.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    return [(p.name, p.read_text(encoding="utf-8")) for p in files], labels


def posting_lang(name: str, label: dict[str, Any]) -> str:
    if label.get("language"):
        return str(label["language"])
    return "da" if name.upper().startswith("DA") else "en"


def gpu_used_mib() -> int | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False
    )
    try:
        return int(out.stdout.split()[0])
    except (ValueError, IndexError):
        return None


def residency_check(o: Ollama, alias: str, gemma: str, where: str) -> Call:
    """Is the LLM fully in VRAM next to the embedding model? Stored as a raw record (task "residency")."""
    loaded = {m["name"].removesuffix(":latest"): m for m in o.ps()}
    missing = [n for n in (gemma, EMBED_MODEL) if n not in loaded]
    partial = [n for n, m in loaded.items() if m.get("size_vram", 0) < m.get("size", 0)]
    detail = {"missing": missing, "partial": partial, "gpu_mib": gpu_used_mib()}
    return Call(alias, "residency", where, not missing and not partial, 0.0, detail=detail)


def load_previous(raw_path: Path, rerun: list[str]) -> list[Call]:
    """For --resume: calls already in the raw file, minus those of the models being rerun."""
    if not raw_path.exists():
        return []
    previous = [Call(**json.loads(line)) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [c for c in previous if c.model not in rerun]


def run(args: argparse.Namespace) -> None:
    postings, labels = load_postings(Path(args.postings))
    profile_path = DATA_ROOT / "profile" / "cv.md"
    profile = profile_path.read_text(encoding="utf-8") if profile_path.exists() else FICTIONAL_PROFILE
    table = model_table(args.num_ctx)
    aliases = [a.strip() for a in args.models.split(",") if a.strip()]
    for a in aliases:
        if a not in table:
            sys.exit(f"unknown model alias {a!r}; choose from {sorted(table)}")
    tasks = set(args.tasks.split(","))

    o = Ollama(args.ollama)
    stem = datetime.now().astimezone().date().isoformat() + (f"-{args.tag}" if args.tag else "")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"{stem}-raw.jsonl"
    kept = load_previous(raw_path, aliases) if args.resume else []
    calls: list[Call] = []
    started = time.perf_counter()

    with raw_path.open("w", encoding="utf-8") as raw:
        for c in kept:
            calls.append(c)
            raw.write(json.dumps(c.__dict__, ensure_ascii=False) + "\n")
        if kept:
            print(f"resumed: kept {len(kept)} calls of {sorted({c.model for c in kept})}", flush=True)

        def record(c: Call) -> None:
            calls.append(c)
            raw.write(json.dumps(c.__dict__, ensure_ascii=False) + "\n")
            raw.flush()
            if c.task == "residency":
                if not c.ok:
                    print(f"  BAD {c.model:<9} residency {c.posting}: {c.detail}", flush=True)
                return
            flag = "ok " if c.ok else "BAD"
            think = "" if c.think is None else f" think={c.think}"
            print(f"  {flag} {c.model:<9} {c.task:<7} {c.posting:<18}{think} {c.wall_s:6.1f}s", flush=True)

        for alias in aliases:
            cfg = table[alias]
            print(f"== {alias} ({cfg.name}, num_ctx={cfg.num_ctx})", flush=True)
            o.unload_all()
            is_gemma = alias == "ajs-gemma"
            model_tasks = [t for t in TASKS_BY_MODEL[alias] if t in tasks]

            def guarded(fn: Any, *a: Any, task: str, posting: str, think: bool | None = None, alias: str = alias) -> None:
                try:
                    record(fn(*a))
                except Exception as e:  # noqa: BLE001 - a failed call is a benchmark result
                    record(Call(alias, task, posting, False, 0.0, think=think, detail={"error": str(e)[:300]}))

            for name, text in postings:
                label = labels.get(name, {})
                if is_gemma:
                    # Analysis phase needs bge-m3 next to the LLM (step 9 of the workflow).
                    o.embed(text[:8000])
                for rep in range(args.repeats):
                    if "tool" in model_tasks:
                        guarded(task_tool, o, cfg, name, text, label, task="tool", posting=name)
                    if "extract" in model_tasks:
                        guarded(task_extract, o, cfg, name, text, label, args.json_mode, task="extract", posting=name)
                if "rubric" in model_tasks:
                    for temp in args.rubric_temps:
                        for think in (False, True):
                            guarded(
                                task_rubric,
                                o,
                                cfg,
                                name,
                                text,
                                profile,
                                think,
                                args.json_mode,
                                temp,
                                task="rubric",
                                posting=name,
                                think=think,
                            )
                if is_gemma:
                    record(residency_check(o, alias, cfg.name, f"{name} analysis"))
            if "letter" in model_tasks or "email" in model_tasks:
                for name, text in postings:
                    brief = extract_brief(o, cfg, text)
                    for task, fn in (("letter", task_letter), ("email", task_email)):
                        if task in model_tasks:
                            guarded(fn, o, cfg, name, text, profile, brief, task=task, posting=name)
                    if is_gemma:
                        o.embed(text[:2000])
                        record(residency_check(o, alias, cfg.name, f"{name} generation"))

    total_s = time.perf_counter() - started
    letters = [c for c in calls if c.task in ("letter", "email") and c.detail.get("text")]
    if letters:
        write_ratings(out, stem, letters)
    report = render_report(args, stem, calls, total_s, o.version(), profile_path.exists(), labels)
    report_path = out / f"{stem}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nreport:  {report_path}\nraw:     {raw_path}")
    if letters:
        print(f"ratings: {out / f'{stem}-ratings.csv'}")


def write_ratings(out: Path, stem: str, letters: list[Call]) -> None:
    rng = random.Random()
    rows = letters[:]
    rng.shuffle(rows)
    key: dict[str, str] = {}
    with (out / f"{stem}-ratings.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "posting", "kind", "text", "rating", "comment"])
        for i, c in enumerate(rows, 1):
            rid = f"L{i:02d}"
            key[rid] = c.model
            w.writerow([rid, c.posting, c.task, c.detail["text"], "", ""])
    (out / f"{stem}-key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")


# --- report ------------------------------------------------------------------


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d * 100:.0f}%)" if d else "–"


def speed(cs: list[Call]) -> tuple[float, float]:
    ev, es = sum(c.eval_tokens for c in cs), sum(c.eval_s for c in cs)
    pv, pt = sum(c.prompt_tokens for c in cs), sum(c.prompt_s for c in cs)
    return (ev / es if es else 0.0, pv / pt if pt else 0.0)


def rubric_section(rub: list[Call], temp: float) -> list[str]:
    lines = ["", f"## Rubric scoring: thinking off vs on (ajs-gemma, temperature {temp:g})", ""]
    lines += [
        "| Posting | Total off | Total on | Criteria equal | Wall off s | Wall on s | Thinking chars |",
        "|---|---|---|---|---|---|---|",
    ]
    diffs: list[int] = []
    eq_n = eq_d = 0
    walls: dict[bool, list[float]] = {False: [], True: []}
    for name in dict.fromkeys(c.posting for c in rub):
        off = next((c for c in rub if c.posting == name and c.think is False), None)
        on = next((c for c in rub if c.posting == name and c.think is True), None)
        if not off or not on:
            continue
        walls[False].append(off.wall_s)
        walls[True].append(on.wall_s)
        so, sn = off.detail.get("scores"), on.detail.get("scores")
        eq = "–"
        if so and sn:
            e = sum(so[k] == sn[k] for k in RUBRIC_CRITERIA)
            eq_n, eq_d = eq_n + e, eq_d + len(RUBRIC_CRITERIA)
            eq = f"{e}/{len(RUBRIC_CRITERIA)}"
            diffs.append(abs(off.detail["total"] - on.detail["total"]))
        lines.append(
            f"| {name} | {off.detail.get('total', 'invalid')} | {on.detail.get('total', 'invalid')} | {eq} | "
            f"{off.wall_s:.1f} | {on.wall_s:.1f} | {on.detail.get('thinking_chars', 0)} |"
        )
    if diffs:
        lines += [
            "",
            (
                f"Mean |total off − total on| = {sum(diffs) / len(diffs):.1f} points; criterion agreement "
                f"{pct(eq_n, eq_d)}; mean wall off {sum(walls[False]) / len(walls[False]):.1f} s vs on "
                f"{sum(walls[True]) / len(walls[True]):.1f} s. Schema valid: off "
                f"{pct(sum(c.ok for c in rub if not c.think), len([c for c in rub if not c.think]))}, on "
                f"{pct(sum(c.ok for c in rub if c.think), len([c for c in rub if c.think]))}."
            ),
        ]
    return lines


def render_report(
    args: argparse.Namespace,
    stem: str,
    calls: list[Call],
    total_s: float,
    version: str,
    real_cv: bool,
    labels: dict[str, Any],
) -> str:
    res = [c for c in calls if c.task == "residency"]
    calls = [c for c in calls if c.task != "residency"]
    models = list(dict.fromkeys(c.model for c in calls))
    lines = [
        f"# Model benchmark {stem}",
        "",
        (
            f"- Ollama {version}, `{args.ollama}`; tag `{args.tag or '-'}`; JSON mode `{args.json_mode}`; "
            f"repeats {args.repeats}; this session {total_s / 60:.1f} min{' (resumed)' if args.resume else ''}"
        ),
        (
            f"- Candidate profile: {'DATA_ROOT/profile/cv.md' if real_cv else 'built-in fictional profile'}; "
            f"labels: {'yes' if labels else 'no (tool/extract checks shape only)'}"
        ),
        "",
        "## Summary",
        "",
        "| Model | Tool call correct | job_brief schema valid | Brief fields correct | Gen tok/s | Prompt tok/s | Mean wall s/call |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in models:
        mc = [c for c in calls if c.model == m]
        tool = [c for c in mc if c.task == "tool"]
        ext = [c for c in mc if c.task == "extract"]
        fields = [v for c in ext for v in c.detail.get("fields", {}).values()]
        gen, pp = speed([c for c in mc if c.eval_s])
        wall = sum(c.wall_s for c in mc) / len(mc) if mc else 0
        lines.append(
            f"| {m} | {pct(sum(c.ok for c in tool), len(tool))} | {pct(sum(c.ok for c in ext), len(ext))} | "
            f"{pct(sum(fields), len(fields))} | {gen:.1f} | {pp:.0f} | {wall:.1f} |"
        )

    rub = [c for c in calls if c.task == "rubric"]
    for temp in dict.fromkeys(c.detail.get("temperature", 0.0) for c in rub):
        lines += rubric_section([c for c in rub if c.detail.get("temperature", 0.0) == temp], temp)

    if res:
        peak = max((c.detail.get("gpu_mib") or 0 for c in res), default=0)
        lines += [
            "",
            "## Co-residency (ajs-gemma + bge-m3)",
            "",
            f"- `/api/ps` checks with both models fully in VRAM: {pct(sum(c.ok for c in res), len(res))}",
            f"- Peak `nvidia-smi` memory.used: {peak} MiB",
        ]
        lines += [f"- {c.posting}: missing={c.detail['missing']} partial={c.detail['partial']}" for c in res if not c.ok]

    lines += ["", "## Failures", ""]
    bad = [c for c in calls if not c.ok]
    lines += [f"- {c.model} {c.task} {c.posting}: `{json.dumps(c.detail, ensure_ascii=False)[:300]}`" for c in bad] or ["None."]
    writing = [c for c in calls if c.task in ("letter", "email")]
    if writing:
        lines += [
            "",
            "## Writing checks and rating",
            "",
            "| Task | Checks passed | Mean words |",
            "|---|---|---|",
            *[
                f"| {t} | {pct(sum(c.ok for c in writing if c.task == t), len([c for c in writing if c.task == t]))} | "
                f"{sum(c.detail.get('words', 0) for c in writing if c.task == t) / max(1, len([c for c in writing if c.task == t])):.0f} |"
                for t in ("letter", "email")
            ],
            "",
            "Checks: no `{{ }}` left; letter 150-450 words; email at most 150 words.",
            "",
            (
                f"Rate `{stem}-ratings.csv` (column `rating`, 1–5) without opening `{stem}-key.json`, then run "
                f"`uv run backend/evals/model_bench.py score <path to {stem}-ratings.csv>`."
            ),
        ]
    lines.append("")
    return "\n".join(lines)


def score(args: argparse.Namespace) -> None:
    csv_path = Path(args.csv)
    key_path = csv_path.with_name(csv_path.name.replace("-ratings.csv", "-key.json"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    by: dict[tuple[str, str], list[int]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not row["rating"].strip():
                continue
            model = key[row["id"]]
            r = int(row["rating"])
            by.setdefault((model, row["kind"]), []).append(r)
            by.setdefault((model, "all"), []).append(r)
    if not by:
        sys.exit("No ratings filled in yet.")
    print("| Model | Kind | n | Mean rating |\n|---|---|---|---|")
    for (model, kind), rs in sorted(by.items()):
        print(f"| {model} | {kind} | {len(rs)} | {sum(rs) / len(rs):.2f} |")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the benchmark")
    r.add_argument("--models", default="ajs-gemma")
    r.add_argument("--tasks", default="tool,extract,rubric,letter,email")
    r.add_argument("--repeats", type=int, default=3, help="repeats for the tool and extract tasks")
    r.add_argument("--num-ctx", type=int, default=int(os.environ.get("LLM_NUM_CTX", "32768")))
    r.add_argument("--postings", default=str(DATA_ROOT / "profile" / "eval_postings"))
    r.add_argument("--out", default=str(DATA_ROOT / "evals"))
    r.add_argument("--ollama", default=OLLAMA_URL)
    r.add_argument("--tag", default="", help="suffix for output files, e.g. f16 or q8")
    r.add_argument(
        "--resume",
        action="store_true",
        help="keep the calls already in today's raw file for this tag, except those of --models, which rerun",
    )
    r.add_argument(
        "--json-mode",
        choices=["schema", "json", "none"],
        default="schema",
        help="Ollama `format` for the extract and rubric tasks",
    )
    r.add_argument(
        "--rubric-temps",
        type=lambda v: [float(t) for t in v.split(",")],
        default=[0.0],
        help="comma-separated temperatures; rubric runs thinking off and on at each, e.g. 0,0.3",
    )
    r.set_defaults(fn=run)
    s = sub.add_parser("score", help="summarise a rated ratings CSV")
    s.add_argument("csv")
    s.set_defaults(fn=score)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
