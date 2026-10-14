# 07 — Feed intake & posting fetcher

**Depends on:** 06 · **Branch:** `feat/07-intake`

_Rewritten 2026-10-12: intake moved from IMAP to Jobindex RSS (D3 revised). The old email design is in git history._

## Goal
Poll Jobindex RSS feeds (D3) behind a `JobSource` interface, store items idempotently, get full posting text (D4), and drive the per-job pipeline.

## Prerequisites (ask user)
- The Jobindex searches to follow: give each one as a feed URL (`https://www.jobindex.dk/jobsoegning.rss?<same query string as the search page>`), or as search terms the agent turns into URLs. The user should check each URL in a browser first.

## Verified facts (2026-10-12, architecture §1)
- Feed is RSS 2.0, **ISO-8859-1**, `ttl` 1440. `<item><title>` is `"<job title>, <company>"`; `<link>` is `https://www.jobindex.dk/vis-job/<id>`; `<description>` is escaped HTML containing logo, title, company and a snippet.
- Not yet checked: how many items a feed returns (paging) and where `vis-job` redirects for jobs posted on employer sites. Check both with `curl` before coding and record them under Follow-ups.

## Steps
1. **Settings:** `JOBINDEX_FEEDS` (comma-separated URLs), `FEED_POLL_INTERVAL_MIN=1440` (never below the feed `ttl`), `FETCH_USER_AGENT`, `FETCH_DENYLIST=linkedin.com`. Replace the `IMAP_*` block in `infra/.env.example` and pass these settings to the `worker` service in compose.
2. **`JobSource` interface** `worker/sources/base.py`: `fetch() -> list[RawJob]`, where `RawJob = {source, source_job_id, url, title, company, snippet_html, published_at}`. One implementation now: `worker/sources/jobindex_rss.py` (`httpx` + `feedparser`, or stdlib `xml.etree` with explicit ISO-8859-1 decoding). The `source_job_id` is the last path segment of `vis-job/<id>`. Title and company come from splitting the item title on its **last** `", "`; fall back to the description HTML when there is no comma.
3. **Store:** upsert `feed_item` on (`source`, `source_job_id`) so repeats are skipped. Mark `processed_at` only after the pipeline has created or deduplicated the posting.
4. **Scheduler:** separate `worker` service in compose (same image as backend, command `python -m ajs.worker`) using APScheduler; it exposes no ports. Manual trigger via `POST /api/v1/workflow/run` (plan 06) enqueues the same job. Use a Postgres advisory lock so only one pipeline run happens at a time.
5. **Posting fetcher** `services/fetch_posting.py`, for each job:
   - if the snippet is at least ~150 words and lists requirements → use it;
   - else `httpx` GET on the `vis-job` URL (timeout 15 s, the configured UA, follow redirects, honor robots.txt) + `trafilatura.extract`. Store the final URL after redirects as `source_url` only if it is on the employer's domain; otherwise keep the `vis-job` URL;
   - a domain on the denylist → skip the fetch;
   - failure or short result → status `needs_manual_text` (UI lets the user paste; plan 12 adds the field).
   - Be polite: at most 1 request/second to jobindex.dk.
6. **Pipeline orchestrator** `worker/pipeline.py` (architecture §5):
   - Analysis: for each new `feed_item` → `find` (A5, `source_job_id` first) → stop if it exists (`duplicate`) → create the row → fetch text → Analysis+Match flow (plan 08) → `low_match` or `awaiting_match_review`.
   - Generation: for each `matched` posting (the user approved it at gate 1, D9) → Generation flow (plan 09). Runs on the same worker tick and also when `POST /match-decision` enqueues it.
   - Isolate each job in try/except → `error` status with the message; retry only transient errors (max 2).
   - Until 08/09 exist, flows are called through an interface that tests can stub.
7. **Fixtures:** 2 feed snapshots in `backend/tests/fixtures/jobindex/`: one real, trimmed to 3 items (public data, no personal data), and one synthetic with an edge case (company name containing a comma, missing company).

## Acceptance criteria
- [x] Tests: RSS parsing (encoding, title/company split, id extraction), idempotent re-poll (same id ignored), fetch fallback chain, denylist, pipeline with stubbed flows covering dedup-stop, low-match-stop and stop at `awaiting_match_review`.
- [x] `JobSource` has one implementation, and the pipeline imports only the interface.
- [ ] Against the live feed (user present): one poll ingests items; a second poll adds no duplicates. _Checked 2026-10-14 with a generic public query against the scratch DB (5 in, 0 on repeat); repeat with the user's own feeds._

## Out of scope
LLM analysis (08). An email `JobSource` (later follow-up if wanted; it needs OAuth for Microsoft 365, see D3).
