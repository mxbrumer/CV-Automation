# 13 — Frontend queue tab

**Depends on:** 11 (uses endpoints from 06) · **Branch:** `feat/13-queue`

## Goal
Work through approved applications one at a time and record the outcome.

## Workflow diagram (D11, first step of this plan)
Add a Mermaid `flowchart` to `README.md`: Jobindex feed → dedup → analysis + match → **Gate 1: Matches** (user) → drafts (CV, cover letter, recruiter email) → **Gate 2: Review** (user) → Queue → manual submit. Show the stop branches (`duplicate`, `low_match`, `match_declined`, `declined`) and label the local-only parts (Ollama). Render it with `npx @mermaid-js/mermaid-cli` to `docs/assets/workflow.png` (≈1200 px wide, white background) and commit both. The raw URL works only once this is on `main`; until then, point the image at the branch URL for testing.

## UI `/queue`
1. Card for `GET /api/v1/queue/next` showing: company, title, match score, position "3 of 12".
2. **Blob storage location**: Windows host path (from API, plan 06 step 6) with **Copy path** button; list of final files (latest approved PDFs + recruiter email).
   **Recruiter email (D11):** show subject, recruiter address and rendered body with the workflow diagram. **Copy as rich text** writes a `ClipboardItem` with `text/html` (body + `<img src="https://raw.githubusercontent.com/mxbrumer/Moving-To-Denmark/main/docs/assets/workflow.png" width="600" alt="Workflow diagram">`) and a `text/plain` fallback. Use the remote URL, not a `data:` URI, because classic Outlook usually drops `data:` images on paste. Separate **Copy subject** and **Copy address** buttons.
3. **Application website** link (`source_url`, opens in a new tab).
4. Actions → `POST /queue/{id}/action`:
   - **Mark submitted** → `submitted`, sets `submitted_at`.
   - **Reject** → `declined` (user chose not to apply), optional reason.
   - **Skip** → moves to end of queue (no status change).
   Confirmation for submitted/reject; undo toast for 5 s (calls a reverse transition endpoint, or delays the call).
5. Empty queue state with link to Review.

## Acceptance criteria
- [ ] With seed data: skip reorders, submit increments the dashboard "submitted" tile, reject removes from queue.
- [ ] Component tests for all three actions + empty state; backend queue tests from plan 06 still pass.
- [ ] Manual check (user present): paste the copied email into a new message in **classic and new Outlook**; the diagram shows in both. If it doesn't, record what happened under Follow-ups and ask the user before choosing another route.

## Out of scope
Tracking employer responses (possible follow-up: `outcome` field for interview/offer/rejection).
