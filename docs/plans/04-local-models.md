# 04 — Local models setup & evaluation

**Depends on:** 03 · **Branch:** `feat/04-models`

## Goal
Pin the local models, confirm with a small repeatable benchmark that `gemma4:12b` covers every LLM role (D1, revised 2026-09-28), and fix `num_ctx` and the VRAM strategy.

## Re-run (added 2026-10-12): do this section; steps 1–6 below were done on Ollama 0.34.4
Ollama is now 0.40.3, and the rubric (D10), output language (A2) and templates (A6) changed, so every number in `docs/model-evaluation.md` is stale.

**Prerequisites (stop and ask if missing):** the user has finished `DATA_ROOT/profile/cover_letter_template.md` (drafted 2026-10-12, rewritten by the user) and `recruiter_email_template.md`, and has rated the old `2026-09-30-*-ratings.csv` files or said to skip them.

**Harness changes** in `backend/evals/model_bench.py`:
- Default `--models ajs-gemma`; keep the baseline configs but do not run them.
- `RUBRIC_CRITERIA` → `skills`, `experience`, `domain` (D10). Add `location`, `relocation_ok`, `required_languages`, `danish_required` to the `job_brief` extraction schema instead, and check them against the labels.
- `letter` task: fill `cover_letter_template.md` with brief + CV, **always English** (A2), full letter not a paragraph.
- New `email` task: fill `recruiter_email_template.md`; check that every `{{ }}` placeholder is resolved and the body is ≤ 150 words.
- Both writing outputs go to the blind ratings CSV (1–5, the user rates).

**Run:** `scripts/pull-models.ps1` (recreates `ajs-gemma` if needed), then the full suite with `--repeats 3`. Re-check on 0.40.3: the `format: "json"` + `think: false` bug (Follow-up 04 → 08, 09), and co-residency with `bge-m3` plus the eviction order. Update or delete those Follow-ups to match.

**Then:** set the D8 threshold from the rated rubric totals (the default is 55; pick the value that separates postings the user labels "would apply" from the rest), and replace the stale tables in `docs/model-evaluation.md`.

## Known facts (from architecture §1; don't re-test unless versions change)
- Usable VRAM is about 10.7 GB, because Windows holds about 1.5 GB of the 12 GB.
- `gemma4:12b`: 7.6 GB file, 256K max context, tools + thinking per the Ollama library. **Not yet tested on this machine.**
- Baselines already measured: Mimir Q4_K_M has 4096 ctx, 4.2 GB VRAM, good Danish, **no tool calls**. qwen2.5:14b has 9.5 GB VRAM and correct tool calls.

## Steps
1. **`scripts/pull-models.ps1`**: pulls `gemma4:12b` and `bge-m3`. A `-Baselines` switch also pulls `hf.co/danish-foundation-models/DFM-Mimir-GGUF:Q4_K_M` and `qwen2.5:14b` for the benchmark comparison. Idempotent; prints `ollama list`.
2. **Ollama server settings**: test `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` (user-level env vars, Ollama restart needed). Keep them only if Gemma 4 output quality holds and VRAM use drops (`ollama ps`). Document the result and the setup command in `docs/model-evaluation.md`.
3. **Gemma Modelfile** `infra/ollama/Gemma.Modelfile` → `ollama create ajs-gemma`: `FROM gemma4:12b`, keep the embedded chat template and stop tokens (see `ollama show --modelfile`), set `num_ctx`. Start at 16384 and pick the largest value that stays 100% GPU with `bge-m3` loaded at the same time (`ollama ps`). Temperature is set per request, not in the Modelfile, so agent and writer calls share one loaded model. App config values, not hard-coded: `LLM_AGENT_MODEL=ajs-gemma`, `LLM_WRITER_MODEL=ajs-gemma`, `EMBED_MODEL=bge-m3`.
4. **Benchmark harness** `backend/evals/model_bench.py` (run with `uv run`): calls the Ollama HTTP API directly. Inputs: 5–10 real postings (DA + EN) the user provides in `DATA_ROOT/profile/eval_postings/` (ask user). Tasks, run on `ajs-gemma` and on the baselines:
   - tool call: the `find_application(company, title)` test from architecture §1; measure correct-call %.
   - extraction → `job_brief` JSON schema (title, company, language, contact, must_have[], nice_to_have[], keywords[]); measure schema validity %.
   - rubric scoring with Gemma thinking **off** vs **on** (`think` request option); record agreement and wall time.
   - cover-letter paragraph in the posting language, Gemma vs Mimir. Shuffle and hide the model names; the user rates 1–5 in a CSV.
   - tokens/s and wall time per model.
   Output `DATA_ROOT/evals/<date>.md` (not committed); commit only the harness and a summary table in `docs/model-evaluation.md` (no personal content).
5. **VRAM strategy**: document in `docs/model-evaluation.md` the chosen `keep_alive` values and confirm `ajs-gemma` + `bge-m3` stay co-resident at 100% GPU through a full analysis + generation run. If they don't, first lower `num_ctx`; if that fails, record `qwen3.5:9b` (6.6 GB) as the tested fallback.
6. **Token budgeting helper** spec (implemented in plan 09): count tokens with the Gemma 4 tokenizer (`tokenizer.json` via the `tokenizers` lib). If the Hugging Face repo is gated, fall back to a conservative characters-per-token estimate. Check either method against Ollama's `prompt_eval_count`. It enforces the writer budgets in architecture §5, scaled to the chosen `num_ctx`.

## Acceptance criteria
- [x] `ollama list` shows `ajs-gemma` and `bge-m3`.
- [x] Benchmark runs end-to-end; summary committed in `docs/model-evaluation.md`.
- [x] Decision recorded: `num_ctx`, `keep_alive`, thinking on/off per task, flash attention/KV cache settings.
- [x] If Gemma fails the tool-call test, or Mimir clearly wins the blind Danish writing rating, **stop and ask the user** before changing D1. (Gemma 18/18 on tools; Mimir not re-run, waived by the user because output is English-only.)
- [x] Re-run (2026-10-12) (letter ratings done, email ratings deferred by the user, D8 threshold 55 confirmed against would-apply labels): suite run on Ollama 0.40.3 with the 3-criterion rubric, the template-based letter and the email tasks; ratings filled in; D8 threshold confirmed with the user; Follow-ups 04 → 08/09 re-verified.

## Out of scope
LangFlow flows (08/09).
