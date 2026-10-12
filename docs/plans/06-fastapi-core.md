# 06 — FastAPI core & tool endpoints

**Depends on:** 05 · **Branch:** `feat/06-api`

## Goal
Backend API that owns DB + blob storage, serves the frontend, exposes "tool" endpoints for LangFlow, and triggers LangFlow runs.

## Layout
`backend/src/ajs/` → `main.py`, `settings.py`, `db/`, `domain/` (normalize, status transitions, scoring math), `api/ui/*.py`, `api/tools/*.py`, `services/` (`blob.py`, `langflow_client.py`, `render.py` stub), `worker/` (plan 07).

## Steps
1. **Settings** (`pydantic-settings`): `DATABASE_URL`, `DATA_ROOT`, `BACKEND_API_KEY`, `LANGFLOW_URL`, `LANGFLOW_API_KEY`, flow ids, `OLLAMA_BASE_URL`, `MATCH_THRESHOLD`, dedup params (A5).
2. **Auth:** all routes require `X-API-Key == BACKEND_API_KEY` (A1). Frontend dev proxy injects it; no user accounts.
3. **Status transitions** in `domain/status.py`: an allowed-transitions map (architecture §6); every change goes through one function that writes `posting_event`. Invalid transition → 409.
4. **Tool endpoints** (`/api/v1/tools`, called by LangFlow; request/response are Pydantic models whose JSON schemas LangFlow components mirror):
   | Method + path | Purpose (brief step) |
   |---|---|
   | `POST /postings/find` `{company, title, source_url?, source_job_id?}` → `{exists, posting_id?, reason}` | 3–4 (A5 logic, pg_trgm `similarity()`) |
   | `POST /postings` → `{posting_id}` | 5 (upserts company) |
   | `PATCH /postings/{id}/analysis` `{language, recruiter_*, job_brief}` | 6–8 |
   | `PATCH /postings/{id}/match` `{embedding_score, rubric_score, rationale}` → computes `match_score` (D8), sets `awaiting_match_review`/`low_match` | 9–10 |
   | `GET /profile/cv-sections` → CV split by `##` headings with ids | 9, 12 |
   | `GET /profile/templates/{kind}` | 13–14 |
   | `POST /postings/{id}/folder` → path | 11 |
   | `POST /postings/{id}/artifacts` `{kind, markdown}` → saves `.md`, renders `.pdf`, new version | 12–15 |
   | `POST /postings/{id}/status` `{to, note}` | error/side statuses |
5. **UI endpoints** (`/api/v1`): `GET /stats` (dashboard counts, plan 11), `GET /postings?status=&q=&page=`, `GET /postings/{id}` (with artifacts + events), `GET/PUT /postings/{id}/artifacts/{kind}` (manual edit = new version), `POST /postings/{id}/match-decision` `{approve|decline, note?}` → `matched` (enqueues generation, plan 09) or `match_declined` (gate 1, D9), `POST /postings/{id}/approve` → `approved` + `queue_position`, `GET /queue/next`, `POST /queue/{id}/action` `{submitted|declined|skip}`, `GET /files/{id}/{filename}` (serve PDF), `POST /workflow/run` (manual trigger).
6. **Blob service**: all paths resolved under `DATA_ROOT/applications`; reject path traversal; folder name `<yyyy-mm>_<company-slug>_<title-slug>_<id>`; file names `cv_v{n}.md/.pdf` etc. Return the Windows host path for UI display by mapping the container path → `HOST_DATA_ROOT` setting.
7. **LangFlow client**: `run_flow(flow_id, input_value, tweaks)` → `POST {LANGFLOW_URL}/api/v1/run/{flow_id}` with header `x-api-key`. Verify the exact endpoint/body against LangFlow 1.12 API docs (https://docs.langflow.org/) before coding. Record each call in `workflow_run`.
8. **Render stub**: `render.markdown_to_pdf(md, css) -> bytes` interface only; implemented in plan 09. Dockerfile should already install WeasyPrint system libs (pango, harfbuzz) so 09 needs no infra change.
9. **Dockerfile** (`python:3.12-slim`, uv, non-root user); enable `backend` service in compose (remove `profiles` gate).
10. Export OpenAPI to `backend/openapi.json` via a script; the frontend generates types from it (plan 11). CI checks it is up to date.

## Acceptance criteria
- [ ] `uv run pytest` covers: dedup find (exact URL, fuzzy match, no match), status transition validation (incl. gate 1: only `awaiting_match_review` accepts a match decision), match score math + threshold, blob path traversal rejection, queue ordering incl. skip.
- [ ] `docker compose up backend` → `GET /health` 200; `/docs` lists all endpoints.
- [ ] Requests without API key → 401.

## Out of scope
IMAP/worker (07), PDF rendering (09), LangFlow flows (08).
