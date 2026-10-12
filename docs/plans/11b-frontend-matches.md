# 11b — Frontend matches tab (gate 1)

**Depends on:** 08, 11 · **Branch:** `feat/11b-matches`

_Added 2026-10-12 (D9, D10)._

## Goal
Gate 1: the user confirms or declines each posting the matcher surfaced before any drafts are generated.

## UI `/matches`
1. List of postings in `awaiting_match_review` (`GET /api/v1/postings?status=awaiting_match_review`), sorted by `match_score` descending. Each row shows company, title, score, posting language and published date.
2. Expanding a row (or `/matches/:id`) shows:
   - score breakdown: embedding vs rubric, with must-haves marked met/partial/missing and the cited CV sections;
   - **flags** (D10), shown as chips and never scored: posting language `da`, `danish_required`, `required_languages`, `location`, `relocation_ok`;
   - the match rationale and a source link (`source_url`, new tab);
   - the posting text, collapsed by default.
3. Actions → `POST /postings/{id}/match-decision`:
   - **Approve** → `matched`; the toast says drafts are being generated (plan 09 runs in the background).
   - **Decline** → `match_declined` with an optional reason (free text, kept in `posting_event`, useful for tuning the rubric later).
   - Undo toast for 5 s (delay the call).
4. Keyboard: `j`/`k` move, `a` approve, `d` decline.
5. Empty state linking to Home ("run pipeline now").

## Acceptance criteria
- [ ] With seed data (plan 05 seeds `awaiting_match_review` rows that have flags): approve moves an item to `matched`, decline to `match_declined`, and the badge count updates.
- [ ] Flags render; a `danish_required` posting shows its chip.
- [ ] Component tests for approve, decline, undo and empty state (API mocked).
- [ ] Works at 1280 px and 390 px.

## Out of scope
Draft review (12), queue (13).
