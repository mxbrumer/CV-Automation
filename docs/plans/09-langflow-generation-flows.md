# 09 — LangFlow flows: document generation

**Depends on:** 08 · **Branch:** `feat/09-flows-generation`

## Goal
Gemma-powered writer steps for brief steps 11–15: tailored CV, cover letter, recruiter email, saved as Markdown + PDF.

## Prerequisites (ask user)
User places Markdown versions of their inputs in `DATA_ROOT/profile/` (A6): `cv.md` (with `##` sections and bullet items), `cover_letter_template.md`, `recruiter_email_template.md` (all English, A2; the user's templates exist since 2026-10-12). Provide `*.example.md` stubs in repo `docs/profile-examples/` showing expected structure and placeholders, using the user's `{{ placeholder }}` syntax. Some placeholders hold instructions, not field names (e.g. `{{ 2-3 top requirements from the posting related to AI and LLMs }}`), so the writer resolves each placeholder by reading it as an instruction. If the user's files are Word/PDF, offer to convert them (pandoc) but let the user review the result.

## Flow `generate_documents`
Input `{posting_id}`. Deterministic chain, not a tool-calling agent, so output stays predictable and the writer model can be swapped by config (D1). Each LLM node = Ollama model from global variable `LLM_WRITER_MODEL` (`ajs-gemma`, plan 04), thinking off unless plan 04 recorded otherwise:
1. Triggered only for `matched` postings (approved at gate 1, D9). Custom component loads the posting (`GET /postings/{id}`), brief, CV sections and templates; creates the folder (`POST /folder`).
2. **Evidence selector** (no LLM; uses stored bge-m3 embeddings): pick top CV bullets per must_have → within the CV evidence budget (architecture §5).
3. **CV Writer**: rewrite/reorder bullets toward the brief, in one call for the whole CV if it fits the writer budget, else per section and merge. Never invent employers, dates, degrees, or skills not present in the profile `cv.md`. Output → `cv_v1.md` in the posting folder. All documents are written in **English**, even for Danish postings (A2).
4. **Letter Writer** — `cover_letter_template.md` + brief + evidence → `cover_letter_v1.md` (≤ 1 page, ~300–400 words).
5. **Email Writer** — fills `recruiter_email_template.md`; uses the recruiter's name if a contact exists, else a generic greeting → `recruiter_email_v1.md` (subject + ≤ 150 words). The template's "diagram below" is delivered by the Queue tab (D11), so the writer leaves no image placeholder. A deterministic check fails the step if any `{{ }}` is left unresolved.
6. **Budget guard** custom component: counts tokens with the Gemma tokenizer or fallback estimate (plan 04 step 6); trims evidence first, then template examples, to keep every call within the chosen `num_ctx` incl. output (architecture §5 budgets).
7. **Fact check** (`LLM_AGENT_MODEL`, same run; no model swap needed): compare each output against `cv.md`; flag unsupported claims into `posting_event` note and a `warnings` field shown in the review UI. Do not auto-rewrite.
8. Save each via `POST /artifacts`; set status `generated`.

## Backend: PDF rendering
Implement `services/render.py` with `markdown-it-py` → HTML + CSS (`backend/src/ajs/templates/pdf/{cv,letter}.css`, A4, clean single-column) → WeasyPrint PDF. Unit test: renders Danish characters (æøå) and fits a 1-page letter.

## Acceptance criteria
- [ ] One synthetic matched application → folder with `cv_v1.md/.pdf`, `cover_letter_v1.md/.pdf`, `recruiter_email_v1.md`; status `generated`.
- [ ] Danish posting → English documents (A2); no `{{ }}` left in any output.
- [ ] Token guard test: oversized input is trimmed, never fails Ollama with context overflow.
- [ ] Hallucination guard: fact-check flags a planted fake skill in a test.
- [ ] Flows exported; `pytest -m llm` updated.

## Out of scope
Review UI (12).
