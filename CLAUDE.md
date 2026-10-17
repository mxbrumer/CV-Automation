# AI Job Search

Local-only pipeline: jobs pasted into the Add job form → LangFlow agents (Ollama) → FastAPI/Postgres → React review UI. Applications are drafted automatically and always submitted manually. Two human gates: Matches (approve a match) and Review (approve drafts).

- Design and decisions D1–D11, assumptions A1–A6: [docs/architecture.md](docs/architecture.md)
- Work is split into session-sized plans: [docs/plans/README.md](docs/plans/README.md) (use `/execute-plan`)

## Hard rules
- **Local LLMs only**, through Ollama. No cloud LLM SDKs or API keys anywhere.
- **FastAPI is the only owner of the DB schema and blob storage.** LangFlow calls FastAPI tool endpoints and never touches Postgres app tables.
- **No personal data in git**: CV, templates, emails, `.env`, anything under `DATA_ROOT/profile/`. The repo holds only `*.example.md` stubs.
- `DATA_ROOT` (default `C:\dev\JobSearchData`) stays **outside OneDrive**.
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`); one branch per plan, `feat/NN-short-name`.
- Do not re-decide architecture. If a decision proves wrong, stop, ask the user, then update architecture.md.
- Stay in scope of the current plan; put discoveries under **Follow-ups** in the plans README.

## Layout
`backend/` FastAPI (uv) · `frontend/` Vite+React+TS · `langflow/flows` exported flow JSON, `langflow/components` custom components · `infra/` compose, Dockerfiles, `.env.example` · `scripts/` PowerShell helpers · `docs/` · `prompts/`

## How to run
- First time: copy `infra/.env.example` to `infra/.env` and fill in the secrets.
- Stack: `scripts/dev.ps1 up|down|ps|logs [svc]|reset-db|backup`. `up` starts Docker Desktop if needed, creates the `DATA_ROOT` folders and waits until services are healthy.
- UIs: LangFlow http://127.0.0.1:7860 (superuser from `infra/.env`), Phoenix http://127.0.0.1:6006, Postgres `127.0.0.1:5432`.
- Governance check: `python scripts/governance_check.py` (rules in [docs/governance.md](docs/governance.md)); `scripts/dev.ps1 prune-traces` deletes old Phoenix traces.
- Backend tests: `cd backend; uv run pytest`
- Frontend tests: `cd frontend; npm test`
- Browser e2e (Playwright, seeded fake data, stubbed chat): `cd frontend; npm run test:e2e`; `E2E_REAL_LLM=1` uses the local Ollama for the chat step. Full pipeline e2e: `scripts/e2e.ps1` (throwaway `DATA_ROOT`, about 10 minutes)

## Model roles (all via Ollama)
| Model | Role |
|---|---|
| `gemma4:12b` (app alias `ajs-gemma`) | every LLM role: orchestration, tool calls, extraction, rubric scoring, document writing, chat edits |
| `bge-m3` | multilingual embeddings |

Agent and writer model names are separate config values (`LLM_AGENT_MODEL`, `LLM_WRITER_MODEL`), never hard-coded. DFM-Mimir and qwen2.5:14b are benchmark baselines only (plan 04).

VRAM is 12 GB, about 10.7 GB usable. Gemma (7.6 GB file) and bge-m3 should stay resident together; plan 04 verifies this and sets `num_ctx`. Use one `num_ctx` everywhere, since a different value reloads the model.

## Windows notes
- Shell is PowerShell 5.1: no `&&`/`||`; chain with `;` and check `$?`.
- Containers reach native Ollama at `http://host.docker.internal:11434`. This works with Ollama's default `127.0.0.1` binding (verified in plan 03), so do not set `OLLAMA_HOST=0.0.0.0`.
- Files are mounted into Linux containers, so keep LF line endings (`.gitattributes` enforces it).
