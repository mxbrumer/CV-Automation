# 03 — Docker infrastructure

**Depends on:** 01 · **Branch:** `feat/03-infra`

## Goal
One `docker compose` stack for Postgres, Phoenix, LangFlow, backend and frontend, with data outside OneDrive (D6) and Ollama on the host (D2).

## Steps
1. **`DATA_ROOT`** (default `C:\dev\JobSearchData`): script `scripts/init-data-root.ps1` creates
   `applications/`, `profile/`, `postgres/`, `phoenix/`, `langflow/`, `backups/`. Idempotent.
2. **`infra/.env.example`** (copy to `infra/.env`, gitignored). Vars: `DATA_ROOT`, `POSTGRES_USER/PASSWORD/DB` (app DB `jobsearch`), `LANGFLOW_DB`, `LANGFLOW_SUPERUSER`, `LANGFLOW_SUPERUSER_PASSWORD`, `LANGFLOW_API_KEY`, `BACKEND_API_KEY`, `OLLAMA_BASE_URL=http://host.docker.internal:11434`, `PHOENIX_COLLECTOR_ENDPOINT`, `IMAP_*` (plan 07), `MATCH_THRESHOLD=70`.
3. **`infra/docker-compose.yml`** services (all ports bound to `127.0.0.1` per A1):
   | service | image | port | notes |
   |---|---|---|---|
   | `postgres` | `postgres:17` | 5432 | bind mount `${DATA_ROOT}/postgres`; `infra/postgres/init/01-databases.sql` creates `jobsearch` and `langflow` DBs; healthcheck `pg_isready` |
   | `phoenix` | `arizephoenix/phoenix` (pin a version tag) | 6006 (UI + OTLP HTTP), 4317 (gRPC) | storage at `${DATA_ROOT}/phoenix` |
   | `langflow` | `langflowai/langflow:1.12.x` (pin exact patch) | 7860 | `LANGFLOW_DATABASE_URL=postgresql://…@postgres:5432/langflow`, `LANGFLOW_AUTO_LOGIN=false`, `LANGFLOW_COMPONENTS_PATH=/app/custom_components` mounted from `langflow/components`, `PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006` |
   | `backend` | build `backend/Dockerfile` | 8000 | mounts `${DATA_ROOT}/applications` and `${DATA_ROOT}/profile` (read-only) |
   | `frontend` | build `frontend/Dockerfile` (nginx serving built assets) | 5173 | dev mode uses Vite outside Docker |
   - `extra_hosts: ["host.docker.internal:host-gateway"]` on langflow + backend.
   - backend/frontend services use `profiles: ["app"]` until plans 06/11 create them, so `docker compose up` works now.
4. **Ollama reachability:** verify from a container: `docker compose run --rm langflow curl -s http://host.docker.internal:11434/api/tags`. If it fails, set user env `OLLAMA_HOST=0.0.0.0:11434`, restart Ollama, and document it in CLAUDE.md. (Ollama must not be exposed beyond localhost — check Windows Firewall blocks inbound 11434.)
5. **`scripts/dev.ps1`** with verbs `up`, `down`, `logs [svc]`, `ps`, `reset-db` (with confirmation), `backup` (`pg_dump` both DBs to `${DATA_ROOT}/backups/<date>.sql`). Must start Docker Desktop if the daemon is not running and wait for it.
6. Update CLAUDE.md "How to run" if commands differ.

## Acceptance criteria
- [x] `scripts/dev.ps1 up` → `postgres`, `phoenix`, `langflow` healthy (`docker compose ps`).
- [x] LangFlow UI at http://127.0.0.1:7860 logs in with superuser; `langflow` DB contains its tables (`\dt` via `docker compose exec postgres psql`).
- [x] Phoenix UI at http://127.0.0.1:6006.
- [x] Ollama reachable from the langflow container (step 4).
- [x] Nothing written under the OneDrive repo path at runtime.
- [x] `docker compose config -q` passes (CI infra job).

## Out of scope
Backend/frontend code and Dockerfile contents beyond placeholders (06, 11).
