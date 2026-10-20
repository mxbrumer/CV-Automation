# Operations

Everything runs locally: Docker for Postgres, Phoenix, LangFlow, the backend and the frontend; Ollama natively on Windows. All ports bind to `127.0.0.1`. Commands are PowerShell 5.1 from the repo root.

## Where data lives

All runtime data is under `DATA_ROOT` (from `infra/.env`, default `C:\dev\JobSearchData`), outside OneDrive and outside git.

| Folder | Holds | In `dev.ps1 backup`? |
|---|---|---|
| `postgres\` | the app database and LangFlow's database | yes (as a dump) |
| `applications\` | one folder per posting: drafts (`.md`), PDFs, versions | **no** |
| `profile\` | your `cv.md` and the two templates | **no** |
| `backups\` | database dumps | n/a |
| `phoenix\` | traces (contain CV and posting text; pruned after `PHOENIX_RETENTION_DAYS`, 90) | no |
| `langflow\` | LangFlow config dir | no (flows live in git: `langflow/flows`) |
| `evals\` | benchmark and rating files | no |

## Start, stop, inspect

```
scripts/dev.ps1 up              # start (and wait until healthy)
scripts/dev.ps1 ps              # status
scripts/dev.ps1 logs backend    # follow one service (langflow, backend, postgres, ...)
scripts/dev.ps1 down            # stop, data is kept
```

Containers restart on their own (`restart: unless-stopped`) when Docker starts. Container logs rotate at 3 files of 10 MB per service. UIs: app http://127.0.0.1:5173, LangFlow http://127.0.0.1:7860, Phoenix http://127.0.0.1:6006.

## Backup

`scripts/dev.ps1 backup` writes `DATA_ROOT\backups\<date>_<time>.sql` with both databases. It does **not** copy `applications\` or `profile\`; copy those folders too (for example to an external disk). Phoenix traces are not worth backing up.

### Weekly schedule (Windows Task Scheduler)

Run once in PowerShell, adjusting the repo path (this command has **not been run on this machine yet**; check it with the query below). The task runs every Sunday at 03:00, only while you are logged in, and `dev.ps1` starts Docker Desktop if it is not running:

```
schtasks /Create /TN "AI Job Search backup" /SC WEEKLY /D SUN /ST 03:00 /RL LIMITED /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\AI-Job-Search\scripts\dev.ps1 backup"
```

Check it with `schtasks /Query /TN "AI Job Search backup"` and remove it with `schtasks /Delete /TN "AI Job Search backup" /F`. A dump is about 20 MB; delete old ones in `DATA_ROOT\backups` by hand when you want the space.

## Restore

```
scripts/dev.ps1 restore 2026-10-14_180907.sql
```

It asks you to type `restore`, stops the backend, LangFlow and frontend, **drops both databases**, loads the dump and starts everything again. Only files inside `DATA_ROOT\backups` can be restored. `applications\` and `profile\` are untouched, so restore them from your own copy if they are lost.

The command was tested on 2026-10-14 on a throwaway stack (a marker row was added, backed up, deleted and restored). A dump also loads into a fresh Postgres 17 started with the same `POSTGRES_USER`, which is how to check a backup without touching the live stack.

## Update

- **Code**: `git pull`, then `scripts/dev.ps1 up` (rebuilds the backend and frontend images). Database migrations run when the backend starts.
- **A release**: the pinned images are `ghcr.io/<owner>/ajs-backend:X.Y.Z` and `ajs-frontend:X.Y.Z`; flows come as `langflow-flows-vX.Y.Z.zip` on the GitHub Release.
- **Models**: `scripts/pull-models.ps1` pulls `gemma4:12b` and `bge-m3` and rebuilds the `ajs-gemma` alias from `infra/ollama/Gemma.Modelfile`. Change the model in `infra/.env` (`LLM_AGENT_MODEL`, `LLM_WRITER_MODEL`, `EMBED_MODEL`) and re-run `scripts/import-flows.ps1` so LangFlow's variables follow. Keep one `num_ctx` everywhere: a different value reloads the model.
- **LangFlow version**: change the tag in `infra/docker-compose.yml` (`langflowai/langflow:1.12.3`), run `scripts/dev.ps1 up`, then `scripts/import-flows.ps1`. Custom components are mounted from `langflow/components`; restart the LangFlow container after changing one. After editing a flow in the UI, run `scripts/export-flows.ps1` and commit the JSON.
- **Phoenix traces**: `scripts/dev.ps1 prune-traces`.
- **Workflow diagram**: after changing the Mermaid diagram in `README.md`, copy it to `docs/assets/workflow.mmd` and re-render the PNG that the recruiter email links to: `npx -p @mermaid-js/mermaid-cli mmdc -i docs/assets/workflow.mmd -o docs/assets/workflow.png -s 1.6 -b white`.

## Tests

- Backend `cd backend; uv run pytest` (needs a scratch `DATABASE_URL`), frontend `cd frontend; npm test`.
- Browser suite `cd frontend; npm run test:e2e` (fake data, stubbed chat; own database `jobsearch_e2e`).
- Whole pipeline `scripts/e2e.ps1` (takes the stack down, runs it on `C:\dev\JobSearchData-e2e` with 4 synthetic jobs sent through `POST /postings`, then restores your stack; about 10 minutes with a warm model).

## Troubleshooting

- **Port already allocated**: another stack publishes it; `docker ps`.
- **Every pipeline run fails with 403**: `LANGFLOW_API_KEY` is missing or stale (it is lost when LangFlow's database is reset or restored from a dump made before the key existed). Create a new key and run `scripts/dev.ps1 up`.
- **First start on an empty `DATA_ROOT` fails**: fixed on `test/14-e2e` and released from v0.1.0 (the Postgres health check uses TCP); on an older checkout run `scripts/dev.ps1 up` a second time.
- **Posting stuck in `new`** (the backend restarted during a run, or the run failed before LangFlow answered): press **Process pending** on Home. It re-runs analysis for `new` postings and drafting for `matched` ones.
- **Old `needs_manual_text` postings**: manual intake (plan 15) no longer sets this status, and the plan 15 migration deleted the feed postings that had it. To retry such a job, paste it again in **Add job**.
