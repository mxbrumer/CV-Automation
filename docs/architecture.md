# Architecture & Decisions

Source brief: [prompts/project-setup.md](../prompts/project-setup.md). This file is the synthesized design; the executable work lives in [plans/](plans/README.md).

## 1. Verified environment (2026-09-28)

| Item | Value | How verified |
|---|---|---|
| CPU / RAM | i5-12600K (10C/16T), 31.8 GB | `Get-CimInstance` |
| GPU | RTX 5070, 12 GB VRAM | `nvidia-smi` |
| Disk | C: 722 GB free | `Get-CimInstance Win32_LogicalDisk` |
| OS | Windows 11 Pro 10.0.26200 | |
| Docker | 29.6.1 (Docker Desktop, daemon was **not running**) | `docker --version`, `docker ps` failed on npipe |
| WSL default distro | `podman-machine-default` (Docker Desktop uses its own distro; not a blocker) | `wsl --status` |
| Ollama | 0.34.4, native Windows | `ollama --version` |
| LangFlow Desktop | 1.12.0 installed (not used by this project, see D2) | dist-info in `%LOCALAPPDATA%\com.LangflowDesktop` |
| Python / Node / uv | 3.12.10 / 24.14.1 / uv present | |
| gh CLI, psql | not installed | |
| Repo location | inside OneDrive (sync risk, see D6) | |

### Model tests (run against local Ollama)
| Model | Size in VRAM | Result |
|---|---|---|
| `hf.co/danish-foundation-models/DFM-Mimir-GGUF:Q4_K_M` | 4.2 GB, 100% GPU | Arch `hrm_text`, 1.79B params, **4096 ctx**. Danish QA correct. `format=json` extraction correct. ~118 tok/s. **Tool-call test: no tool call emitted** despite `tools` capability. |
| `qwen2.5:14b` (installed) | 9.5 GB, 100% GPU | Tool-call test: correct `find_application(company, title)` call. |
| `gemma4:12b` as `ajs-gemma` (plan 04, 2026-09-30) | 8.2 GB at `num_ctx` 32768 with q8_0 KV cache; 10.8 GB total GPU with `bge-m3` loaded, 100% GPU | Tool call 18/18, `job_brief` extraction 18/18 (Danish and English), ~63 tok/s. Danish writing rating pending. Details: [model-evaluation.md](model-evaluation.md). |

Windows itself holds about 1.5 GB of VRAM (`nvidia-smi`, 2026-09-28), so roughly 10.7 GB is usable. qwen2.5:14b + Mimir (≈13.7 GB) could not both be resident, which is why the first version of D1 batched work per model. `gemma4:12b` + `bge-m3` (≈8.8 GB before KV cache) are expected to fit together, so the revised D1 needs no model swapping; plan 04 confirms this.

Sources: [Gemma 4 on Ollama](https://ollama.com/library/gemma4), [DFM-Mimir card](https://huggingface.co/danish-foundation-models/DFM-Mimir), [DFM-Mimir-GGUF](https://huggingface.co/danish-foundation-models/DFM-Mimir-GGUF), [Langflow install](https://docs.langflow.org/get-started-installation), [Langflow Postgres](https://docs.langflow.org/configuration-custom-database), [Langflow + Phoenix](https://docs.langflow.org/integrations-arize), [Langflow Ollama](https://docs.langflow.org/bundles-ollama).

## 2. Decisions (confirmed with user)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Single local LLM (revised 2026-09-28).** `gemma4:12b` = all LLM roles: orchestration, parsing, tool calls, extraction, rubric scoring, document writing (CV, cover letter, recruiter email) and chat edits. Document writing stays in fixed, non-agent flow steps. `bge-m3` (Ollama) = multilingual embeddings. All via Ollama; no cloud LLMs. The app reads the agent model and the writer model from two separate settings, so a different writer can be swapped in by config. **DFM-Mimir** is kept only as the Danish-writing baseline in plan 04's benchmark. | Chosen by the user on 2026-09-28, replacing the earlier hybrid (`qwen2.5:14b` for agents + DFM-Mimir for writing; the original brief named Mimir as primary). Gemma 4 12B fits in 12 GB next to bge-m3, so there is no model swapping. It has native tool calls, and its long context removes Mimir's 4k budget limits. If plan 04 shows Mimir clearly writes better Danish, or Gemma fails tool calls, stop and ask the user before changing D1 again. |
| D2 | **LangFlow in Docker Compose**, image `langflowai/langflow` pinned to `1.12.x`. Ollama stays **native on Windows** (GPU); containers reach it at `http://host.docker.internal:11434`. | Reproducible, versioned. |
| D3 | **Email intake via IMAP polling** (app password). | Provider-agnostic. |
| D4 | **Posting text: mixed.** Use email body if it contains a full description; else fetch URL; else mark `needs_manual_text` for user paste. LinkedIn pages are not scraped. | Emails vary. |
| D5 | **Documents authored in Markdown, rendered to PDF** (WeasyPrint in backend container). | Easiest for LLM + chat editing. |
| D6 | **Data outside OneDrive.** `DATA_ROOT` (default `C:\JobSearchData`) holds blob storage, profile inputs (CV, templates), and Docker bind mounts. Repo code may stay in OneDrive. | Avoid sync locks/corruption. |
| D7 | **GitHub + GitHub Actions + release-please**, Conventional Commits, single SemVer for the whole repo. | Basic CI/CD with release versions. |
| D8 | **Hybrid match score** 0–100 = `w_e * embedding_cosine + w_r * rubric_score`, weights and threshold in config (defaults 0.4/0.6, threshold 70). | Stable + explainable. |

## 3. Assumptions (not asked; change if wrong)
- A1 Single local user; frontend/API bound to localhost; no auth beyond a shared API key between services.
- A2 Generated documents use the **posting's language** (Danish or English). Other languages → status `unsupported_language`, stop.
- A3 Frontend chat editing also uses local models (`gemma4:12b`), consistent with "LLM calls must be local".
- A4 Application submission is always manual (user opens link from the Queue tab).
- A5 Duplicate = same `source_url`/source job id, OR pg_trgm similarity ≥ 0.85 on normalized company + title within 120 days (configurable).
- A6 User inputs (CV, cover letter template, recruiter email template) are converted to Markdown and kept in `DATA_ROOT/profile/`, never committed. Repo holds only `*.example.md` stubs.

## 4. Component responsibilities

```
IMAP ─► FastAPI worker (scheduler) ──run flow──► LangFlow (agents) ──► Ollama (host GPU)
                 │  ▲                                  │
                 │  └──── tool endpoints (REST) ◄──────┘
                 ▼
          PostgreSQL (app DB + langflow DB)      Blob: DATA_ROOT/applications/<id>/
                 ▲
React UI ──► FastAPI ◄── Phoenix (traces from LangFlow + FastAPI, OTLP)
```

- **FastAPI** is the single owner of the DB schema and blob storage. LangFlow never touches Postgres/app tables directly; it calls FastAPI tool endpoints. FastAPI also schedules IMAP polling and iterates jobs (one LangFlow run per job → idempotent, retryable).
- **LangFlow** hosts the multi-agent logic as flows exported to `langflow/flows/*.json`, plus custom components in `langflow/components/`.
- **Phoenix** receives traces from LangFlow (native integration) and FastAPI (OpenTelemetry).

## 5. Workflow mapping (brief steps → implementation)

| Step | Owner | Model |
|---|---|---|
| 1 Receive email | FastAPI IMAP poller; stores `email_message` by Message-ID (idempotent) | – |
| 2 Split into jobs | LangFlow **Intake agent** → JSON list of jobs (title, company, url, snippet) | gemma |
| 3–4 Dedup, stop if exists | FastAPI `POST /tools/applications/find` (A5), called per job | – |
| 5 Insert row | `POST /tools/applications` → `fact_application` status `new` (upserts `dim_company`) | – |
| (D4) Get full text | FastAPI fetcher (httpx + trafilatura) | – |
| 6 Language | **Analyst agent** (+ cheap `lingua`/langdetect pre-check) | gemma |
| 7 Recruiter contact | Analyst agent, JSON output; regex pre-extract emails/phones | gemma |
| 8 Keywords/requirements | Analyst agent → `job_brief` JSON (≤ 600 tokens) | gemma |
| 9 Similarity score | **Matcher agent**: bge-m3 cosine (CV sections vs brief) + rubric (D8) | bge-m3, gemma |
| 10 Stop if weak | status `low_match` (terminal) | – |
| 11 Create folder | `POST /tools/applications/{id}/folder` → `DATA_ROOT/applications/<yyyy-mm>_<company>_<title>_<id>/` | – |
| 12 Tailored CV | **CV Writer**: whole-CV rewrite in one call if it fits the writer budget, else section by section | gemma |
| 13 Cover letter | **Letter Writer**: brief + top CV evidence + template | gemma |
| 14 Recruiter email | **Email Writer** (only if contact found, else generic) | gemma |
| 15 Save artifacts | `POST /tools/applications/{id}/artifacts` → `.md` + rendered `.pdf`; status `generated` | – |

Run order: the worker runs steps 2–10 for all new jobs (analysis phase), then 12–14 for all matches (generation phase). With one LLM this is no longer needed to avoid model swaps; it is kept so a batch of emails is triaged before the slower writing starts. `gemma4:12b` and `bge-m3` stay resident with a long `keep_alive`. Every caller uses the same `num_ctx`, because a different value makes Ollama reload the model.

Writer context budget per call, assuming `num_ctx` 16384 (plan 04 sets the final value and may scale these): system+instructions ≤ 1000, job brief ≤ 1000, CV evidence ≤ 4000, template/section ≤ 1500, output ≤ 2000 tokens. The rest is headroom.

## 6. Application status lifecycle
`new → analyzed → low_match` (terminal) | `→ matched → generating → generated → approved (queued) → submitted | declined`; `skip` only reorders the queue. Side statuses: `duplicate`, `needs_manual_text`, `unsupported_language`, `error`. Every change is written to `application_event`.

## 7. Repo layout (target)
```
.claude/            Claude Code settings, skills, agents
.github/            workflows, PR template, release-please config
backend/            FastAPI (uv project), Alembic, tests
frontend/           Vite + React + TypeScript
langflow/           flows/*.json (exported), components/*.py (custom)
infra/              docker-compose.yml, Dockerfiles, init SQL, .env.example
scripts/            PowerShell helpers (dev up/down, pull models, export flows)
docs/               architecture.md, plans/
prompts/            original briefs
```
