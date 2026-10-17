# 15 — Manual job intake

**Depends on:** 14 · **Branch:** `feat/15-manual-intake`

_Agreed with the user on 2026-10-17 (D3 and D4 revised). The Jobindex RSS intake and the posting fetcher from plan 07 are removed; they stay in git history._

## Goal
The user pastes each job description into an **Add job** form. The posting then runs through the existing analysis, gate 1, generation, gate 2 and queue exactly as before. No feed polling, no web fetching, no worker service.

## Why
The feed snippet is a teaser, and trafilatura on Jobindex or employer pages often returns a partial or wrong text (Workday and other JS pages return nothing). Nothing checked that a fetched text was the whole description, so thin text went straight into scoring.

## Decisions (do not re-decide)
- **Form fields:** company and title (required), application URL (optional), description (required, plain textarea). Under ~150 words shows a warning; it does not block.
- **Dedup on submit (A5):**
  - Same URL as a live posting → refused, with a link to that posting. The partial unique index on `source_url` makes a second row impossible anyway.
  - Similar company and title within the window → the UI shows the match with **Add anyway** / **Cancel**. Add anyway resubmits with `force=true`.
- **After a submit:** the posting is stored with `source='manual'` and `source_job_id = NULL`, and the analysis run starts at once in the background. That is the same locked run the paste box used.
- **Scoring, the `low_match` cutoff and gate 1 do not change** (D8, D9). Reworking them for hand-picked jobs is a later plan.
- **Removed:**
  - `JobindexRssSource`, the `JobSource`/`RawJob` seam and `split_title`;
  - `PostingFetcher`, trafilatura and robots handling;
  - the feed and fetch settings and the denylist;
  - the `needs_manual_text` paste section in Review;
  - the `worker` service.
- **"Run pipeline now" becomes "Process pending":** it re-runs analysis for `new` postings that have text, and generation for `matched` ones. This is the recovery path after a lost background run, for example a backend restart in the middle of a run.
- **Migration, run without a backup (the user's choice):**
  - delete the stranded feed postings with every child row;
  - drop `feed_item` and `fact_posting.feed_item_id`;
  - keep the `needs_manual_text` enum value, because removing a Postgres enum value means rebuilding the type.
- **Egress:** the backend no longer reaches the public web. Every httpx client must be pinned to its hosts, which closes security finding 1 (the fetcher SSRF).

## Steps
1. **Migration `0002_manual_intake`** (`backend/alembic/versions/`):
   - Collect the ids of `fact_posting` rows with `source = 'jobindex'` and (`status = 'needs_manual_text'` or (`status = 'new'` and `posting_text IS NULL`)).
   - Delete their `chat_message`, `application_artifact`, `workflow_run` and `posting_event` rows, then the postings. No blob files exist for these statuses; if `artifact_folder` is set on any of them, log the folder and leave the files alone.
   - Drop the `fact_posting.feed_item_id` FK and column, then `feed_item`.
   - Downgrade recreates the empty table and column. Deleted rows are not restored; say so in the docstring.
   - Update `db/models.py` (remove `FeedItem` and `feed_item_id`) and extend `tests/test_migrations.py`.
2. **Status machine** (`domain/status.py`): remove the `NEW → NEEDS_MANUAL_TEXT` edge. Keep the `NEEDS_MANUAL_TEXT` entry so the enum stays total.
3. **Pipeline runner:**
   - Move `Pipeline` (minus `store_feed_items`, `intake_item` and `_apply_fetch`), `run_once` and the advisory lock from `ajs/worker/` to `ajs/services/pipeline.py`.
   - `run_analysis` becomes `analyze_pending` only.
   - Delete `ajs/worker/` (sources, `__main__`, scheduler) and the `apscheduler` and `trafilatura` dependencies.
   - `api/ui/postings.py:run_pipeline` imports the new module.
4. **Create endpoint** `POST /api/v1/postings` (UI router):
   - Body: `{company, title, url?, text, force=false}`.
   - Runs `postings.find_duplicate` (source `manual`, `source_url=url`).
   - Same URL → `409` `{reason: "same_url", posting}`. Fuzzy match without `force` → `409` `{reason: "similar", posting}`.
   - Otherwise it creates the posting with `posting_text` and `source_url`, commits, queues `run_pipeline` and returns `201` with the summary.
   - Remove `feed_item_id` from the tool `POST /tools/postings` schema.
5. **Remove the paste path:**
   - `PATCH /postings/{id}/posting-text` and its schema;
   - `services/fetch_posting.py` and `worker/sources/`;
   - the jobindex test fixtures;
   - the feed and fetch tests in `test_intake.py`.

   Rename what is left of `test_intake.py` to `test_pipeline.py`.
6. **Process pending:** rename `POST /workflow/poll` to `POST /workflow/process-pending` (same background job, no feed step). Regenerate `backend/openapi.json` (`uv run python scripts/export_openapi.py`) and the frontend types (`npm run gen:api`).
7. **Settings and infra:**
   - Remove `jobindex_feeds`, `feed_poll_interval_min`, `fetch_*` and `feed_urls`/`denylist` from `settings.py`.
   - Remove the `worker` service from `docker-compose.yml` and the matching block from `infra/.env.example`.
   - Remove `worker` from the stop lists in `scripts/dev.ps1` (reset-db, restore).
   - Settings use `extra="ignore"`, so the stale keys left in the user's own `infra/.env` are harmless. Tell the user they can delete them.
8. **Egress guard** (`services/egress.py`):
   - Make `only_hosts` a required argument.
   - Rewrite the module docstring: the allowed hosts are LangFlow, Ollama for chat, and Phoenix through OTLP.
   - Add a test that every `egress_hook(` call in `backend/src` passes `only_hosts`.
   - Add a rule to `scripts/governance_check.py` and `docs/governance.md`.
   - Record finding 1 as closed in the plans README.
9. **Frontend:**
   - New route `/add` with page `AddJob.tsx`, as a tab right after Home: Home, Add job, Matches, Review, Queue.
   - The form uses the four fields with labels. The word count shows next to the textarea, with a warning under 150.
   - A `409 similar` response shows the matched posting (company, title, status, link) with Add anyway / Cancel. A `409 same_url` response shows the link only.
   - On success: a toast, the form clears, and stats/postings queries are invalidated.
   - Remove `PasteBox` and `useNeedsText` from Review.
   - Home: the button becomes "Process pending", and the empty state points to Add job.
   - Component tests cover the form, the warning, both 409 cases and success.
10. **Tests and e2e:**
    - Backend tests for the endpoint: create, same-URL refusal, similar plus force, and validation. Keep the pipeline tests that still apply.
    - `scripts/e2e.ps1`: drop the fixture feed server, `JOBINDEX_FEEDS` and the worker probe. Post the 4 fixture jobs through `POST /postings` (move them from `scripts/e2e/www/feed.xml` to `scripts/e2e/jobs.json`). Assert that the copy is refused with `409`, then the same low_match / match_declined / generated outcomes.
    - Playwright (`frontend/e2e/flow.spec.ts`): add a first step that submits a job on Add job and sees it stored. In `ENV=test` the background run is a no-op, so assert the stored row, not analysis.
    - `seed_dev.py`: seed `source='manual'`.
11. **Docs:**
    - `architecture.md` (D3, D4, A5, §4, §5 and §6 were already revised with this plan);
    - `CLAUDE.md` (first line);
    - README: intro, quick start step 2 and the Mermaid diagram (paste a job → dedup → analysis → gate 1 → …);
    - `docs/assets/workflow.mmd` and `workflow.png` (render with `mmdc -s 1.6`, as in plan 13);
    - `docs/operations.md` (the worker and `needs_manual_text` lines);
    - propose a new `gh repo edit --description` text to the user, and do not run it without approval.

## Acceptance criteria
- [ ] `cd backend; uv run pytest` and `cd frontend; npm test` pass; `python scripts/governance_check.py` passes.
- [ ] `alembic upgrade head` on a copy of real data (the scratch DB seeded with `seed_dev.py` plus a hand-made `needs_manual_text` jobindex posting with an event and a workflow run) deletes that posting and its children, and keeps every other row.
- [ ] `scripts/e2e.ps1` passes: 1 duplicate refused (409), 1 low_match, 1 match_declined, 1 generated with all artifacts.
- [ ] Playwright suite passes locally and in CI, including the Add job step.
- [ ] No reference to `JOBINDEX_FEEDS`, `PostingFetcher`, `trafilatura`, `feed_item` or the `worker` service remains outside `docs/plans/0*.md`, the Alembic history and the CHANGELOG (`git grep` check).
- [ ] User check (user present): add one real job through the form on the real stack, see it scored on Matches.

## Out of scope
- Reworking scoring or gate 1 for hand-picked jobs (follow-up).
- Any discovery source, including `docs/assets/Danish-Companies.csv` (follow-up).
- Rich-text or HTML paste conversion.
- LangFlow flow changes: `AJS Set Status` keeps `needs_manual_text` as an unused option.
