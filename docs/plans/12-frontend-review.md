# 12 — Frontend review tab & chat editing

**Depends on:** 09, 11 · **Branch:** `feat/12-review`

## Goal
Human-in-the-loop review: see generated documents next to templates, refine them via a local-LLM chat, approve into the queue.

## Backend additions (same session)
- `POST /api/v1/postings/{id}/artifacts/{kind}/chat` `{message}` → streams (SSE) a revised full Markdown document plus a short explanation. Uses Ollama model `LLM_AGENT_MODEL` (**ajs-gemma**, A3) directly from the backend via `httpx` (not LangFlow; lower latency). Prompt includes: current document, brief, relevant CV evidence, user instruction, rule "don't invent facts not in cv.md". Persist turns in `chat_message`.
- `POST .../chat/accept` → saves proposal as new artifact version (re-renders PDF).
- `PATCH /postings/{id}/posting-text` for `needs_manual_text` items → re-queues analysis.
- Serve templates read-only: already in plan 06 (`/profile/templates/{kind}`).

## UI
1. **Review list** `/review`: applications in `generated` (and `needs_manual_text` in a second section with a paste box). Columns: company, title, score, language, created. Sort by score.
2. **Review detail** `/review/:id`, three panes (stack on mobile):
   - Left: posting summary (brief, must-haves with met/partial/missing, match rationale, fact-check warnings from plan 09, source link).
   - Center: document tabs **CV / Cover letter / Recruiter email**, each with toggles **Generated | Template**, Markdown preview, edit mode (CodeMirror or textarea), version picker, "Open PDF".
   - Right: chat panel scoped to the active document. Proposal shown as a diff (`diff` lib, word-level) with **Accept** / **Discard**.
3. **Approve** button (enabled when all present docs have been viewed; confirmation dialog) → `POST /approve` → toast + navigate to next item. **Reject** → status `declined` with optional note.
4. Keyboard: `j/k` next/prev application.

## Acceptance criteria
- [x] Chat edit round-trip on a seeded application creates `v2` of the document and a new PDF.
- [x] Approve moves the item to Queue tab with badge count updated. (mocked UI test + backend queue tests; not clicked live)
- [x] Component tests for diff accept/discard and approve flow (API mocked); backend tests for chat endpoint with Ollama mocked.
- [x] No request leaves localhost (checked in code and bundle, not in a browser network tab).

## Out of scope
Queue tab (13).
