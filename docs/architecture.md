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

### Re-verified 2026-10-12
| Item | Value | How verified |
|---|---|---|
| Ollama | **0.40.3** (plan 04 numbers below were measured on 0.34.4 and are stale; plan 04 re-runs) | `ollama --version` |
| gh CLI | 2.101.0 installed | `gh --version` |
| Repo location | `C:\dev\AI-Job-Search`, outside OneDrive (D6 revised) | copied with `robocopy`; the OneDrive copy is to be deleted by the user |
| Mailbox | `brumeranalytics.com` is Microsoft 365 from GoDaddy: MX `brumeranalytics-com.mail.protection.outlook.com`, SPF `include:secureserver.net`. Exchange Online needs OAuth for IMAP (no app passwords), and app registration or consent may be blocked in a GoDaddy-run tenant. Hence D3 revised. | `Resolve-DnsName` |
| Jobindex RSS | `https://www.jobindex.dk/jobsoegning.rss?q=<query>` returns `application/rss+xml` (ISO-8859-1, `ttl` 1440). Each `<item><link>` is `https://www.jobindex.dk/vis-job/<id>` (e.g. `h1707174`); `<description>` is escaped HTML with a snippet. | `curl` |
| Outlook | Classic Outlook (Office16) and new Outlook 1.2026.929 are both installed; `.eml` opens in classic | `Get-AppxPackage`, `assoc .eml` |
| Repo `mxbrumer/Moving-To-Denmark` | **public**; the recruiter email links to it | `gh repo view` |

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
| D1 | **Single local LLM (revised 2026-09-28).** `gemma4:12b` = all LLM roles: orchestration, parsing, tool calls, extraction, rubric scoring, document writing (CV, cover letter, recruiter email) and chat edits. Document writing stays in fixed, non-agent flow steps. `bge-m3` (Ollama) = multilingual embeddings. All via Ollama; no cloud LLMs. The app reads the agent model and the writer model from two separate settings, so a different writer can be swapped in by config. **DFM-Mimir** is kept only as the Danish-writing baseline in plan 04's benchmark (2026-10-12: Mimir and qwen are dropped from the plan 04 re-run, because output is English-only per A2 and Mimir failed every tool and JSON test). | Chosen by the user on 2026-09-28, replacing the earlier hybrid (`qwen2.5:14b` for agents + DFM-Mimir for writing; the original brief named Mimir as primary). Gemma 4 12B fits in 12 GB next to bge-m3, so there is no model swapping. It has native tool calls, and its long context removes Mimir's 4k budget limits. If plan 04 shows Mimir clearly writes better Danish, or Gemma fails tool calls, stop and ask the user before changing D1 again. |
| D2 | **LangFlow in Docker Compose**, image `langflowai/langflow` pinned to `1.12.x`. Ollama stays **native on Windows** (GPU); containers reach it at `http://host.docker.internal:11434`. | Reproducible, versioned. |
| D3 | **Manual intake (revised 2026-10-17).** The user pastes each job into the **Add job** form in the UI: company, title, application URL (optional) and the full description. `POST /api/v1/postings` dedups (A5), stores the posting with `source = 'manual'` and starts the analysis run at once in the background. There is no feed polling and no `worker` service; **Process pending** in the UI re-runs anything a lost background run left behind. Was (2026-10-12): Jobindex RSS polling behind a `JobSource` interface; before that, IMAP. | RSS gave a teaser snippet only, and the fetched pages were often partial (D4), so scoring ran on thin text. The user picks jobs by hand anyway, and a paste is the only reliable full text. Plan 15. |
| D4 | **Posting text is what the user pastes (revised 2026-10-17).** The backend never fetches job pages; a description under ~150 words gets a warning in the form, not a block. Was (2026-10-12): RSS snippet, else fetch the `vis-job` page or the employer page with trafilatura, else `needs_manual_text`. | Fetched text was unreliable (teasers, JS-rendered pages, wrong page parts) and nothing checked it was complete. Removing the fetcher also removes the SSRF risk found in the plan 14 security review. |
| D5 | **Documents authored in Markdown, rendered to PDF** (WeasyPrint in backend container). | Easiest for LLM + chat editing. |
| D6 | **Data and repo outside OneDrive (revised 2026-10-12).** `DATA_ROOT` (default `C:\dev\JobSearchData`) holds blob storage, profile inputs (CV, templates), and Docker bind mounts. The repo lives at `C:\dev\AI-Job-Search` (was: inside OneDrive). | Avoid sync locks/corruption of `.venv`, `node_modules` and bind mounts. |
| D7 | **GitHub + GitHub Actions + release-please**, Conventional Commits, single SemVer for the whole repo. | Basic CI/CD with release versions. |
| D8 | **Hybrid match score** 0–100 = `w_e * embedding_cosine + w_r * rubric_score`, weights and threshold in config (defaults 0.4/0.6, **threshold 55**, revised 2026-10-12 from 70; recalibrate on the plan 04 labeled set). The score only triages: the user confirms each match at gate 1 (D9). | Stable + explainable. |
| D9 | **Two human review gates (2026-10-12).** Gate 1 **Matches** tab: postings at or above the threshold wait in `awaiting_match_review`; the user approves (→ `matched`, drafts are generated) or declines (→ `match_declined`). Gate 2 **Review** tab: the user approves the drafts into the queue. UI flow: Matches → Review → Queue. | No GPU time spent drafting unwanted jobs; matches the workflow diagram promised in the recruiter email. |
| D10 | **Location and language are flags, not scored (2026-10-12).** The rubric scores `skills`, `experience`, `domain` only. `location`, `relocation_ok`, `required_languages` and `danish_required` are extracted into `job_brief` and shown as flags at gate 1. | With equal weights a relocating candidate lost 30–40 of 100 points (plan 04, 2026-09-30), which hid good jobs. |
| D11 | **Workflow diagram (2026-10-12).** One Mermaid diagram in `README.md` (Jobindex feed → analysis → gate 1 → drafts → gate 2 → queue → manual submit), also rendered to `docs/assets/workflow.png`. The recruiter email is delivered by a **Copy as rich text** button in the Queue tab: HTML body with an `<img>` pointing to the public `raw.githubusercontent.com` URL of `workflow.png`, so it survives pasting into Outlook (a `data:` URI usually does not). | The template promises a diagram "below"; the user wants it in the email and in the repo. |

## 3. Assumptions (not asked; change if wrong)
- A1 Single local user; frontend/API bound to localhost; no auth beyond a shared API key between services.
- A2 **(revised 2026-10-12, confirmed with user)** Generated documents are **always in English**. Danish postings are processed normally and flagged (`posting_language = da`) at gate 1 and in Review. Languages other than da/en → status `unsupported_language`, stop.
- A3 Frontend chat editing also uses local models (`gemma4:12b`), consistent with "LLM calls must be local".
- A4 Application submission is always manual (user opens link from the Queue tab).
- A5 **(revised 2026-10-17)** Duplicate = same `source_url` (refused: the URL is unique) OR pg_trgm similarity ≥ 0.85 on normalized company AND on normalized title within 120 days (configurable; the user may **Add anyway**). Old `jobindex` rows still match on (`source`, `source_job_id`); manual postings have no job id.
- A6 User inputs are Markdown in `DATA_ROOT/profile/`, never committed: `cv.md`, `cover_letter_template.md`, `recruiter_email_template.md` (renamed 2026-10-12; the old `cover_letter_template.md` held the email). Templates use `{{ placeholder }}` syntax. Repo holds only `*.example.md` stubs.

## 4. Component responsibilities

```
Add job form ─► FastAPI (background run) ──run flow──► LangFlow (agents) ──► Ollama (host GPU)
                 │  ▲                                  │
                 │  └──── tool endpoints (REST) ◄──────┘
                 ▼
          PostgreSQL (app DB + langflow DB)      Blob: DATA_ROOT/applications/<id>/
                 ▲
React UI ──► FastAPI ◄── Phoenix (traces from LangFlow + FastAPI, OTLP)
```

- **FastAPI** is the single owner of the DB schema and blob storage. LangFlow never touches Postgres/app tables directly; it calls FastAPI tool endpoints. FastAPI also starts the pipeline runs (D3: after each Add job submit, gate-1 approval and Process pending), one LangFlow run per job → idempotent, retryable.
- **LangFlow** hosts the multi-agent logic as flows exported to `langflow/flows/*.json`, plus custom components in `langflow/components/`.
- **Phoenix** receives traces from LangFlow (native integration) and FastAPI (OpenTelemetry).

## 5. Workflow mapping (brief steps → implementation)

| Step | Owner | Model |
|---|---|---|
| 1 Receive jobs (D3) | The user submits the Add job form → `POST /api/v1/postings` | – |
| 2 Split into jobs | Not needed: one submit = one job; company and title are form fields. | – |
| 3–4 Dedup, stop if exists | Same endpoint, before the insert (A5): same URL is refused, a similar company and title asks the user | – |
| 5 Insert row | `fact_posting` status `new` with `posting_text` (upserts `dim_company`) | – |
| 6 Language | **Analyst agent** (+ cheap `lingua`/langdetect pre-check) | gemma |
| 7 Recruiter contact | Analyst agent, JSON output; regex pre-extract emails/phones | gemma |
| 8 Keywords/requirements | Analyst agent → `job_brief` JSON (≤ 600 tokens) | gemma |
| 9 Similarity score | **Matcher agent**: bge-m3 cosine (CV sections vs brief) + rubric on skills/experience/domain (D8, D10) | bge-m3, gemma |
| 10 Stop if weak | status `low_match` (terminal); else `awaiting_match_review` | – |
| Gate 1 (D9) | User approves in the **Matches** tab → `matched`, or declines → `match_declined` (terminal) | – |
| 11 Create folder | `POST /tools/postings/{id}/folder` → `DATA_ROOT/applications/<yyyy-mm>_<company>_<title>_<id>/` | – |
| 12 Tailored CV | **CV Writer**: whole-CV rewrite in one call if it fits the writer budget, else section by section | gemma |
| 13 Cover letter | **Letter Writer**: brief + top CV evidence + `cover_letter_template.md`, in English (A2) | gemma |
| 14 Recruiter email | **Email Writer**: fills `recruiter_email_template.md` (only if contact found, else generic greeting); diagram delivered per D11 | gemma |
| 15 Save artifacts | `POST /tools/postings/{id}/artifacts` → `.md` + rendered `.pdf`; status `generated` | – |

Run order (revised 2026-10-17): a submit starts steps 6–10 for that posting at once (background job). Generation (11–15) starts right after gate-1 approval. **Process pending** re-runs both phases for anything left in `new` (with text) or `matched`. `gemma4:12b` and `bge-m3` stay resident with a long `keep_alive`. Every caller uses the same `num_ctx`, because a different value makes Ollama reload the model.

Writer context budget per call, assuming `num_ctx` 16384 (plan 04 sets the final value and may scale these): system+instructions ≤ 1000, job brief ≤ 1000, CV evidence ≤ 4000, template/section ≤ 1500, output ≤ 2000 tokens. The rest is headroom.

## 6. Posting status lifecycle (revised 2026-10-12)
Table `fact_posting` (renamed from `fact_application`: rows exist for every posting, including non-matches). API routes use `/postings`; the blob folder stays `DATA_ROOT/applications/`.

`new → analyzed → low_match` (terminal) | `→ awaiting_match_review → match_declined` (terminal, gate 1) | `→ matched → generating → generated → approved (queued) → submitted | declined` (gate 2 / queue). In the queue, `skip` only moves the item to the end (no status change); `declined` = the user decided not to apply. Employer outcomes (interview/offer/rejection) are a later follow-up. Side statuses: `duplicate`, `unsupported_language`, `error`; `needs_manual_text` is no longer set (manual intake, D3) but stays in the enum. Every change is written to `posting_event`.

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
