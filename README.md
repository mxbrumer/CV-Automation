# AI Job Search

**A private, fully local AI assistant that turns job postings into tailored, reviewed applications.**

I built this for my own job search in Denmark. I paste a job posting into a web form. The system analyses it, scores it against my CV, and asks whether I want to apply. If I approve, it drafts a tailored CV, a cover letter and a recruiter email for me to review and edit. Every model runs on my own GPU through [Ollama](https://ollama.com). No CV or posting text ever leaves the machine, and nothing is sent without me: I submit every application myself.

**Status:** v0.1.0 is released and the full pipeline works end to end. Development continues in small, planned increments (see [Development process](#development-process)).

## What it does

- **Analyses each posting** for language, requirements, recruiter contact, location and Danish-language requirements, in Danish or English.
- **Scores the match** against my CV from 0 to 100. The score combines embedding similarity with an LLM rubric covering skills, experience and domain. Location and language are shown as flags rather than scored, so they don't hide a good role.
- **Two human approval gates.** In *Matches* I approve or decline each scored job. In *Review* I approve the drafts. No GPU time goes into documents I don't want, and nothing goes out without my sign-off.
- **Drafts three documents per job** (CV, cover letter, recruiter email) in Markdown and renders them to PDF.
- **Fact-checks the drafts.** A separate model pass flags any claim about me that isn't backed by my CV, and the warnings appear next to the draft.
- **Chat editing with diffs.** I can ask the local model to change a draft and accept or discard each proposed edit, shown as a diff.
- **Tracks every posting**: deduplication on intake, a full status history, a searchable *Jobs* list, and a *Queue* of approved applications ready to submit.

## How it works

```mermaid
flowchart TD
  paste["Add job<br/>(you paste the description)"] --> dedup{"Already stored?"}
  dedup -- "same URL, or similar and you cancel" --> dup(["not added"])
  dedup -- "no, or you choose Add anyway" --> analyse["Analysis + match<br/>(Ollama, local)"]
  analyse --> thr{"Score at or above threshold?"}
  thr -- no --> low(["low_match"])
  thr -- yes --> g1{{"Gate 1: Matches<br/>(you decide)"}}
  g1 -- decline --> md(["match_declined"])
  g1 -- approve --> draft["Drafts: CV, cover letter, recruiter email<br/>(Ollama, local)"]
  draft --> g2{{"Gate 2: Review<br/>(you decide)"}}
  g2 -- reject --> dec(["declined"])
  g2 -- approve --> queue["Queue"]
  queue -- reject --> dec
  queue --> submit["Manual submit<br/>(you apply yourself)"]
  classDef local fill:#e8f4ea,stroke:#2e7d32
  classDef gate fill:#fff4d6,stroke:#b26a00
  classDef stop fill:#f1f1f1,stroke:#888
  class analyse,draft local
  class g1,g2 gate
  class dup,low,md,dec stop
```

Green steps run on local models. Yellow steps are my decisions.

### Architecture

```
React UI ──► FastAPI ──runs flows──► LangFlow (agent flows) ──► Ollama (local GPU)
               │  ▲                        │
               │  └── tool endpoints ◄─────┘
               ▼
         PostgreSQL + file storage          Phoenix (traces from FastAPI and LangFlow)
```

- **FastAPI** owns the database schema (Alembic migrations), file storage and the status state machine. It starts one LangFlow run per job, so every run is idempotent and can be retried.
- **LangFlow** runs two flows, *analyse and match* and *generate documents*, built from 15 custom Python components. The components call Ollama directly so they can use structured JSON-schema output and control thinking mode. LangFlow reaches the data only through FastAPI tool endpoints, never the database.
- **React** is the review UI, with tabs for Home, Add job, Matches, Review, Queue and Jobs.
- **Arize Phoenix** collects OpenTelemetry traces from both services, linked by a shared session ID.

## Tech stack

| Area | Tools |
|---|---|
| LLMs | Ollama, Gemma 4 12B for every LLM role, bge-m3 embeddings |
| Agent orchestration | LangFlow 1.12 with custom components |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17 (pg_trgm), WeasyPrint |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query, OpenAPI-generated client |
| Observability | Arize Phoenix, OpenTelemetry |
| Testing | pytest, Vitest, Playwright, LLM golden tests, a full-pipeline e2e script |
| Delivery | Docker Compose, GitHub Actions CI, release-please, Conventional Commits, Dependabot |

## Engineering highlights

- **Privacy by design, enforced in code.** A governance check in CI and pre-commit fails the build on any cloud LLM SDK, hosted-model URL, non-Ollama model component or personal file tracked in git. At runtime, every backend HTTP client is pinned to its one allowed host (LangFlow or Ollama), so the backend cannot reach the public web. Rules: [docs/governance.md](docs/governance.md).
- **Models chosen by measurement, not by guess.** I benchmarked candidate models on real Danish and English postings for tool calling, JSON extraction, rubric scoring and writing. Gemma 4 12B passed 18/18 tool calls, and the evaluation set the context size, the thinking-mode policy and the VRAM budget that lets both models stay resident on a 12 GB GPU. A standalone harness is in [backend/evals](backend/evals/model_bench.py). Results: [docs/model-evaluation.md](docs/model-evaluation.md).
- **Reliable structured output from a small model.** Every JSON call uses Ollama's schema-constrained output, with temperatures, retries and a thinking-token cap tuned from the benchmark.
- **Human in the loop.** The two approval gates, the fact-check warnings and editing by diff keep the model as an assistant, not a decision-maker.
- **Recorded decisions.** 11 numbered decisions and 6 assumptions, each with its rationale and revision history (for example, dropping RSS feed intake for pasted text after measuring how incomplete the fetched postings were): [docs/architecture.md](docs/architecture.md).
- **Tested at every layer.** Unit and API tests against a real Postgres, component tests for the UI, Playwright browser tests, static checks on the exported flows, LLM golden tests, and a script that runs the whole stack end to end.

## Development process

I planned the project as a series of session-sized implementation plans ([docs/plans](docs/plans/README.md)), from scaffold and CI through models, schema, API, flows, UI, end-to-end tests and the first release. Each plan has acceptance criteria, and discoveries go into a shared follow-up log. I built it with Claude Code as an AI pair programmer, working under repo rules in [CLAUDE.md](CLAUDE.md) and with a reviewer agent that checks diffs against those rules.

## Run it locally

Requires Windows 11, Docker Desktop, a native Ollama install with a GPU of about 12 GB VRAM, Node 24, Python 3.12 and [uv](https://docs.astral.sh/uv/). From the repo root in PowerShell:

1. Start Ollama and pull the models: `scripts/pull-models.ps1` (about 9 GB).
2. Copy `infra/.env.example` to `infra/.env`, replace every `change-me` and set `BACKEND_API_KEY`. Keep `DATA_ROOT` outside OneDrive.
3. Start the stack: `scripts/dev.ps1 up`.
4. In LangFlow (http://127.0.0.1:7860), sign in as `LANGFLOW_SUPERUSER`, create an API key and set it as `LANGFLOW_API_KEY` in `infra/.env`.
5. Import the flows with `scripts/import-flows.ps1`, then run `scripts/dev.ps1 up` again.
6. Copy the stubs in `docs/profile-examples/` to `DATA_ROOT\profile\` as `cv.md`, `cover_letter_template.md` and `recruiter_email_template.md`, and fill them in. These files never go into git.
7. Open http://127.0.0.1:5173 and paste a job into **Add job**.

Day-to-day operation, backups, upgrades and troubleshooting: [docs/operations.md](docs/operations.md).

## Docs

- [Architecture and decisions](docs/architecture.md)
- [Model evaluation](docs/model-evaluation.md)
- [Governance and tracing](docs/governance.md)
- [Operations](docs/operations.md)
- [Implementation plans and follow-ups](docs/plans/README.md)
- [Original brief](prompts/project-setup.md)
