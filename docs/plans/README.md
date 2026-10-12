# Implementation Plans

Each plan is sized for **one agent session**. Read [../architecture.md](../architecture.md) first; it holds verified facts, decisions (D1–D11) and assumptions (A1–A6) that every plan relies on. Plans 04–14 were revised on 2026-10-12 (Jobindex RSS intake, two review gates, English-only output, `fact_posting` rename); see architecture "revised 2026-10-12" notes. Do not re-decide them; if one proves wrong, stop and ask the user, then update architecture.md.

## Order & status

| # | Plan | Depends on | Status |
|---|---|---|---|
| 01 | [Claude setup & repo scaffold](01-claude-setup-and-scaffold.md) | – | done |
| 02 | [CI/CD & release versioning](02-ci-cd-and-releases.md) | 01 | done |
| 03 | [Docker infrastructure](03-docker-infrastructure.md) | 01 | done |
| 04 | [Local models setup & evaluation](04-local-models.md) | 03 | in progress |
| 05 | [Database schema & migrations](05-database-schema.md) | 03 | todo |
| 06 | [FastAPI core & tool endpoints](06-fastapi-core.md) | 05 | todo |
| 07 | [Feed intake & posting fetcher](07-feed-intake.md) | 06 | todo |
| 08 | [LangFlow flows: analysis → match](08-langflow-analysis-flows.md) | 04, 06 | todo |
| 09 | [LangFlow flows: document generation](09-langflow-generation-flows.md) | 08 | todo |
| 10 | [Observability & governance](10-observability-governance.md) | 08 | todo |
| 11 | [Frontend scaffold & dashboard](11-frontend-dashboard.md) | 06 | todo |
| 11b | [Frontend matches tab (gate 1)](11b-frontend-matches.md) | 08, 11 | todo |
| 12 | [Frontend review tab & chat editing](12-frontend-review.md) | 09, 11 | todo |
| 13 | [Frontend queue tab](13-frontend-queue.md) | 11 | todo |
| 14 | [End-to-end test & v0.1.0 release](14-e2e-and-first-release.md) | all | todo |

Parallelizable after 06: {07, 08, 11}; after 11: {11b (needs 08), 12 (needs 09), 13}.

## Rules for executing agents
1. Set this plan's status to `in progress` at start and `done` at end (in this table).
2. Stay in scope. Out-of-scope discoveries go under **Follow-ups** at the bottom of this file.
3. Work on a branch `feat/NN-short-name`; Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`); open a PR once plan 02 is done.
4. Every plan ends with its **Acceptance criteria** checked and verified by running the listed commands; report failures honestly.
5. No cloud LLM SDKs or API keys anywhere in the app (governance rule; enforced by plan 10).
6. Never commit personal data (CV, templates, emails, `.env`).

## Follow-ups
_(append here)_
- (02) Plans 05 and 11 mention an `x-release-please-version` marker. It is not needed: `release-please-config.json` updates `project.version` in `backend/pyproject.toml` and `version` in `frontend/package.json` through toml/json `extra-files`.
- (02 → 05) CI runs `uv run mypy` with no arguments, so `backend/pyproject.toml` needs `[tool.mypy] files = [...]`. CI provides `DATABASE_URL=postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch_test` (Postgres 17 service).
- (02 → 06, 11) The release workflow builds images with the package directory (`backend/`, `frontend/`) as the Docker build context, so Dockerfiles must not reference files outside it.
- (02 → 14) The release PR is opened with `GITHUB_TOKEN`, so no checks run on it. Either merge it as admin (the ruleset allows admin bypass on PRs only) or add a fine-grained PAT secret `RELEASE_PLEASE_TOKEN`. See `docs/releasing.md`.
- (02 → 14) With no `v0.0.0` tag, release-please ignores the `0.0.0` manifest entry, so `release-please-config.json` sets `initial-version: 0.1.0`. A release PR titled `chore(main): release 0.1.0` stays open until plan 14; do not merge it earlier.
- (03 → 07) _2026-10-12: the `inbox/` part is obsolete (RSS intake, D3); the `worker` reset-db part still applies._ The backend service mounts only `DATA_ROOT/applications` and `DATA_ROOT/profile` (read-only). Plan 07 writes `DATA_ROOT/inbox/`: add that folder to `scripts/init-data-root.ps1` and a mount to `backend`/`worker`. Also add the `worker` service to the stop list in `dev.ps1 reset-db`.
- (03 → 06, 14) `dev.ps1 reset-db` drops the LangFlow DB too, so `LANGFLOW_API_KEY` and imported flows are gone afterwards. Recreate the key in the LangFlow UI and re-import flows (plan 14's e2e script must do this).
- (03 → 08) The LangFlow 1.12.3 image runs Python 3.14; custom components must work on it. Components are mounted read-only and `PYTHONDONTWRITEBYTECODE=1` keeps `.pyc` out of the OneDrive repo.
- (03 → 10) Phoenix stores SQLite data in `DATA_ROOT/phoenix` (`PHOENIX_WORKING_DIR`); telemetry is off in Phoenix and LangFlow. LangFlow has `PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006`, but trace delivery has not been verified.
- (03) This machine had an unrelated `langflow` container (`langflowai/langflow:latest`) publishing port 7860. The user agreed to stop it and set its restart policy to `no`. If `dev.ps1 up` fails with "port is already allocated", check `docker ps` for other stacks.
- (02) On this machine git's OpenSSL backend fails TLS to github.com (likely HTTPS interception by antivirus or a proxy). The repo-local git config sets `http.sslBackend=schannel`, and `uvx` needs `--system-certs`.
- (04 → 08, 09) Request JSON from Gemma 4 with `format: <JSON schema>` (Ollama structured outputs), never `format: "json"`. On Ollama 0.34.4, `format: "json"` with `think: false` makes Gemma emit broken JSON (e.g. `{"thought": 2024.05}`). Always send `think` explicitly: Gemma 4 thinks by default. See `docs/model-evaluation.md`. _Re-verified on Ollama 0.40.3 (2026-10-12): `format: "json"` still 0/6 valid, schema 6/6._ Also retry `job_brief` extraction at temperature 0.5 when the JSON is invalid: one Danish posting failed 3/3 at 0.2 (truncated JSON) and passed 4/4 at 0.5+.
- (04 → 06, 08) Ollama's scheduler evicts `bge-m3` when `ajs-gemma` loads after it, but keeps both when Gemma loads first (re-verified on 0.40.3). The worker should warm up `ajs-gemma` before the first embedding call, and send the same `num_ctx`/`keep_alive` (`LLM_NUM_CTX`, `LLM_KEEP_ALIVE` in `infra/.env.example`) on every call. Those settings and `LLM_AGENT_MODEL`/`LLM_WRITER_MODEL`/`EMBED_MODEL` are not yet passed to any container in `docker-compose.yml`.
- (04 → 05) `backend/evals/model_bench.py` is a standalone uv script (PEP 723 inline deps) because `backend/pyproject.toml` does not exist yet. When plan 05 creates the project, keep `evals/` out of the package and out of `mypy`'s `files` (or type-check it separately).
- (04 → 08) Relocation: **decided 2026-10-12 as D10** (location/language are flags, not scored; threshold 55). With equal weights, location and language cost a relocating candidate 30–40 of 100 points (benchmark totals 48–76 vs the D8 threshold 70). Use thinking on at temperature 0.3, capped at 3072 output tokens, with one retry with thinking off when the cap is hit (`docs/model-evaluation.md`).
