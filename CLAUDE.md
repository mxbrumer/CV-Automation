# AI Job Search

Local-only pipeline: job pasted into the **Add job** form → FastAPI (dedup, store) → LangFlow flows on Ollama (analysis + match, then drafts) → React review UI. Two human gates: **Matches** (approve a match) and **Review** (approve drafts). Applications are always submitted manually.

- Decisions D1–D11, assumptions A1–A6, status lifecycle: [docs/architecture.md](docs/architecture.md)
- Session-sized plans and their **Follow-ups** (the project's gotcha log): [docs/plans/README.md](docs/plans/README.md); run one with `/execute-plan`
- Start/stop, backup, restore, upgrades, troubleshooting: [docs/operations.md](docs/operations.md)

## Hard rules
- **Local LLMs only**, through Ollama. No cloud LLM SDKs, hosts or API keys anywhere.
- **FastAPI is the only owner of the DB schema (Alembic) and blob storage.** LangFlow calls FastAPI tool endpoints (`/api/v1/tools/...`) and never touches Postgres app tables.
- **Every backend `httpx.Client` is pinned**: it has event hooks and calls `egress_hook(only_hosts=...)`. The backend talks only to LangFlow and Ollama; it never fetches the public web.
- **No personal data in git**: CV, templates, emails, `.env`, anything under `DATA_ROOT/profile/`. The repo holds only `*.example.md` stubs.
- `DATA_ROOT` (default `C:\dev\JobSearchData`) stays **outside OneDrive**.
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`); one branch per plan, `feat/NN-short-name`.
- Architecture is decided. If a decision proves wrong, stop, ask the user, then update architecture.md.
- Stay in the current plan's scope; record discoveries under **Follow-ups** in the plans README.

## Layout
- `backend/` FastAPI, package `ajs` in `src/ajs` (`api/tools` for LangFlow, `api/ui` for the frontend, `services`, `domain/status.py` = status machine), Alembic in `alembic/`, `evals/` standalone benchmark script
- `frontend/` Vite + React + TS, Tailwind v4 (tokens in `src/index.css`), typed client `src/api/client.ts`, React Query hooks `src/api/hooks.ts`, Playwright in `e2e/`
- `langflow/` `flows/*.json` (exported), `components/ajs/` custom components, `prompts/` prompt and schema mirror, `tools/` flow build scripts, `tests/`
- `infra/` compose, `.env.example`, Ollama Modelfile, Postgres scripts · `scripts/` PowerShell helpers · `prompts/project-setup.md` original brief only

## Commands
PowerShell from the repo root. CI (`.github/workflows/ci.yml`) runs the same checks.
- Stack: `scripts/dev.ps1 up|down|ps|logs [svc]|reset-db|backup|restore <file>|prune-traces`. `up` does **not** rebuild images: after backend or frontend code changes run `docker compose -f infra/docker-compose.yml build backend frontend` first.
- UIs (all on 127.0.0.1): app :5173, backend :8000, LangFlow :7860, Phoenix :6006, Postgres :5432.
- Backend: `cd backend; uv run ruff check; uv run ruff format --check; uv run mypy; uv run pytest`. Tests **skip silently** without `DATABASE_URL`; use the scratch DB `postgresql+psycopg://jobsearch_scratch:jobsearch@127.0.0.1:5432/jobsearch_test`. The migration test leaves it downgraded, so run `uv run alembic upgrade head` before pointing uvicorn at it.
- Frontend: `cd frontend; npm run lint; npm run typecheck; npm test -- --run; npm run build` (plain `npm test` is watch mode).
- Browser e2e: `cd frontend; npm run test:e2e` (own backend on :8100 with `ENV=test`, DB `jobsearch_e2e`, never the pytest DB). `E2E_REAL_LLM=1` uses local Ollama for chat.
- Full pipeline e2e: `scripts/e2e.ps1` (stack runs on throwaway `C:\dev\JobSearchData-e2e`, real stack is down for ~10 min).
- LangFlow static tests, from `backend/`: `uv run --with jsonschema pytest ../langflow/tests -c ../langflow/tests/pytest.ini --rootdir ../langflow/tests -m "not llm"`. `-m llm` runs the golden tests (needs the stack, Ollama and `DATA_ROOT/profile/cv.md`).
- Governance: `python scripts/governance_check.py` (rules in [docs/governance.md](docs/governance.md)).

## Change cascades
- **API change**: `cd backend; uv run python scripts/export_openapi.py` (a test fails when `openapi.json` is stale), then `cd frontend; npm run gen:api`.
- **Schema change**: new Alembic revision in `backend/alembic/versions/`; migrations run when the backend starts.
- **Component or prompt change**: edit `langflow/components/ajs/*.py` or `langflow/prompts/*.md` (keep its `version:` header), restart LangFlow (`docker compose -f infra/docker-compose.yml restart langflow`), run the flow's builder in `langflow/tools/`, then `scripts/export-flows.ps1` and commit the JSON. Components stay self-contained, since the flow embeds their source.
- **Flow edited in the LangFlow UI**: `/export-flows`.

## Models (all via Ollama)
- `ajs-gemma` (alias of `gemma4:12b`, `infra/ollama/Gemma.Modelfile`) does every LLM role; `bge-m3` does embeddings. Model names come from `LLM_AGENT_MODEL`, `LLM_WRITER_MODEL`, `EMBED_MODEL`, never hard-coded. DFM-Mimir and qwen2.5:14b are benchmark baselines only.
- Flows are fixed chains of custom components that call Ollama `/api/chat` directly (the built-in component cannot send `think`, a schema `format` or `keep_alive`).
- Request JSON with `format: <JSON schema>`; `format: "json"` yields broken JSON from Gemma. Always send `think` explicitly (Gemma thinks by default).
- `num_ctx` 32768 lives in the Modelfile; callers leave `num_ctx` out, because a different value reloads the model. Load Gemma before bge-m3 so both stay resident in the 12 GB VRAM. Details: [docs/model-evaluation.md](docs/model-evaluation.md).

## Environment gotchas
- PowerShell 5.1: chain with `;` and check `$?`. `$env:X = ''` deletes the variable (compose then falls back to `infra/.env`). Keep `.ps1` files ASCII: BOM-less scripts are read as cp1252. Wrap `docker ... 2>&1` in `cmd /c` under `$ErrorActionPreference = 'Stop'`.
- TLS is intercepted on this machine (Norton): set `UV_SYSTEM_CERTS=1` for uv and `NODE_OPTIONS=--use-system-ca` for npm; Docker builds trust `*.crt` in `backend/certs` and `frontend/certs` (git-ignored). Git already uses `http.sslBackend=schannel`.
- Connect to Postgres from Windows on `127.0.0.1`; `localhost` makes each connection take about a minute.
- Containers reach native Ollama at `http://host.docker.internal:11434` with Ollama's default `127.0.0.1` binding; leave `OLLAMA_HOST` unset.
- `dev.ps1 reset-db` also wipes LangFlow: recreate the API key (`LANGFLOW_API_KEY` in `infra/.env`), run `scripts/import-flows.ps1`, then `dev.ps1 up`. A missing or stale key makes every run fail with 403.
- `ENV=test` (stub chat, no pipeline runs) belongs only to the Playwright backend, never in `infra/.env`.
- Files are mounted into Linux containers: keep LF line endings (`.gitattributes` enforces it).
