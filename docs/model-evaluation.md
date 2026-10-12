# Model evaluation (plan 04)

Measured on 2026-09-29/30 on the machine in [architecture.md §1](architecture.md#1-verified-environment-2026-09-28): RTX 5070 12 GB, Windows 11, Ollama 0.34.4 (native). Raw results and reports stay in `DATA_ROOT/evals/` and are not committed. This page holds only aggregates.

## Decisions

| Setting | Value | Why |
|---|---|---|
| App LLM | `ajs-gemma` = `gemma4:12b` + `num_ctx 32768` ([infra/ollama/Gemma.Modelfile](../infra/ollama/Gemma.Modelfile)) | Passes every agent task (below). D1 stands, pending the blind letter rating. |
| `num_ctx` | **32768** everywhere (`LLM_NUM_CTX`) | Largest value that keeps `ajs-gemma` + `bge-m3` reliably co-resident with margin. 64k with an f16 KV cache crashed `bge-m3` on load (CUDA out of memory). With q8_0, 64k loads but leaves only ~1.1 GB, which a browser or other GPU apps can take. |
| `keep_alive` | **`30m`** for both models (`LLM_KEEP_ALIVE`), sent on every call | Gemma reloads in 2–4 s, so a short idle unload is cheap and frees VRAM for the desktop. Same value for both so they expire together. |
| Load order | Warm up `ajs-gemma` **before** the first `bge-m3` call | Ollama's scheduler predicts 8.3 GiB for Gemma and evicts a resident `bge-m3` when Gemma loads second. When Gemma loads first, `bge-m3` "fits alongside", and both then stay resident (checked after every posting: 11/12 and 5/6 OK, the one miss is always this first load). |
| Flash attention | `OLLAMA_FLASH_ATTENTION=1` (user env var) | Already on by default in 0.34.4 (`--flash-attn auto`). Set explicitly because the quantized KV cache requires it. |
| KV cache | `OLLAMA_KV_CACHE_TYPE=q8_0` (user env var) **kept** | Saves ~0.45 GB at 32k (Gemma 8.70 → 8.24 GB dedicated; total GPU 10.98 → 10.77 GB with both models). Agent tasks identical to f16, same speed. |
| Thinking | **off** for tool calls, extraction, writing and chat edits. **on** for rubric scoring at temperature 0.3, capped at 3072 output tokens, retried once with thinking off if the cap is hit | See [Rubric](#rubric-scoring-thinking-off-vs-on). Gemma 4 thinks by default, so every request sends `think` explicitly. |
| JSON output | `format: <JSON schema>` (structured outputs), never `format: "json"` | With `format: "json"` and `think: false`, Gemma 4 emits broken JSON on 0.34.4 (e.g. `{"thought": 2024.05}`, 6/6 failures). With a schema: 18/18 valid. |
| Temperatures | agent 0.2, rubric 0.3, writer 0.7, set per request | The Modelfile sets none, so agent and writer calls share one loaded model. |

### Setup commands

```powershell
scripts/pull-models.ps1            # gemma4:12b, bge-m3, builds ajs-gemma
scripts/pull-models.ps1 -Baselines # also DFM-Mimir and qwen2.5:14b, only for the benchmark

[Environment]::SetEnvironmentVariable('OLLAMA_FLASH_ATTENTION', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KV_CACHE_TYPE', 'q8_0', 'User')
# Then quit Ollama from the tray and start it again (new processes read user env vars at start).
```

Check: the server log (`%LOCALAPPDATA%\Ollama\server.log`) prints `OLLAMA_FLASH_ATTENTION:true` and `OLLAMA_KV_CACHE_TYPE:q8_0`, and a Gemma load logs `K (q8_0)`.

## Benchmark

Harness: [backend/evals/model_bench.py](../backend/evals/model_bench.py) (standalone uv script). Inputs: 6 real postings (3 Danish, 3 English) with hand-made labels (company, title, language, contact present). The rubric and letter tasks use the user's CV. Tool and extraction ran 3 times per posting.

```powershell
uv run backend/evals/model_bench.py run --tag f16 --rubric-temps 0.3
uv run backend/evals/model_bench.py score C:/dev/JobSearchData/evals/<date>-<tag>-ratings.csv
```

### Agent tasks

| Model | `find_application` tool call correct | `job_brief` schema valid | Brief fields correct | Gen tok/s | Prompt tok/s |
|---|---|---|---|---|---|
| **ajs-gemma** (f16 KV) | **18/18** | **18/18** | **72/72** | 62.7 | ~3000 |
| **ajs-gemma** (q8_0 KV) | **18/18** | **18/18** | **72/72** | 63.8 | ~3500 |
| qwen2.5:14b (baseline) | 18/18 | 18/18 | 72/72 | 60.0 | ~7300 |
| DFM-Mimir Q4_K_M (baseline) | 0/18 | 0/18 | – | 79.4 | – |

- "Correct" tool call: `find_application` called with the labelled company and title (normalized match). "Brief fields": language, company, title and contact presence.
- Mimir never emits a tool call (it answers in text). For extraction it fills the 2048-token output cap without producing valid JSON, with both `format: <schema>` and `format: "json"` (0/6 each). It stays a writing baseline only.

### Rubric scoring: thinking off vs on

Five criteria (skills, experience, domain, language, location), each 0–5, total scaled to 0–100.

| Run | Valid off | Valid on | Mean \|off − on\| | Criteria equal | Mean wall off | Mean wall on (ok calls) |
|---|---|---|---|---|---|---|
| f16, temperature 0 | 6/6 | 5/6 | 10.4 | 40% | 3.3 s | 17 s |
| f16, temperature 0.3 | 6/6 | 6/6 | 7.3 | 40% | 4.5 s | 21 s |
| q8_0, temperature 0.3 | 6/6 | 4/6 | 7.0 | 55% | 3.1 s | 19 s |

- **Runaway thinking.** In 3 of 18 thinking calls, Gemma kept rewording its rationale until the 8192-token cap (~130 s) and never answered. With an earlier CV draft that gave no language levels, all 4 thinking calls at temperature 0 did this. Successful thinking calls used at most 1550 tokens and 25 s, so a 3072-token cap catches a runaway in ~50 s. The sample is too small to attribute the two q8_0 runaways to the KV cache: agent tasks were identical, and sampling at 0.3 is random.
- **Thinking off misreads the profile.** It scored an English-native candidate 1–3/5 on language for English postings. Thinking on gave 3–4, and on Danish postings it matched the stated Danish level more closely. Thinking off is cheap but its errors are systematic, so the matcher uses thinking on with the cap and fallback above.
- **Matcher design note for plan 08:** location and language are equal-weight criteria. A candidate who is relocating loses 30–40 points on them, so totals stayed between 48 and 76 even with strong skills and experience scores, which leaves little margin around the D8 threshold of 70. Plan 08 must account for relocation intent (profile statement, criterion weights, or a filter).

### Cover-letter paragraph (Danish and English), blind rating

| Model | Danish mean (n) | English mean (n) |
|---|---|---|
| ajs-gemma | pending | pending |
| DFM-Mimir | pending | pending |

All 12 paragraphs were generated (6 per model, 120–160 words requested). Ratings are pending: the user rates `DATA_ROOT/evals/2026-09-30-f16-ratings.csv`. If Mimir clearly wins the Danish rows, D1 is revisited with the user first.

### VRAM (both models loaded, `nvidia-smi`)

| `num_ctx` | KV cache | Gemma dedicated | Total GPU used | `bge-m3` load | Gen tok/s |
|---|---|---|---|---|---|
| 16384 | f16 | 8.73 GB | 11.02 GB | OK | 62.9 |
| 32768 | f16 | 8.70 GB | 10.98 GB | OK | 63.9 |
| 65536 | f16 | 9.24 GB | 11.52 GB | **crashed once** (CUDA OOM) | 63.8 |
| 32768 | q8_0 | 8.24 GB | 10.77 GB | OK | 63.6 |
| 65536 | q8_0 | 8.59 GB | 11.13 GB | OK | 64.1 |

- Total includes ~1.7 GB used by Windows and desktop apps.
- Gemma 4 keeps a full-length KV cache in only 8 of 48 layers. The other 40 use a 1536-cell sliding window, so context is cheap: f16 needs 16 KiB per token plus a fixed ~480 MiB, and q8_0 halves both.
- Ollama's `ollama ps` showed "100% GPU" even when VRAM was oversubscribed. The 64k f16 crash was only visible in the server log. Check the server log and `nvidia-smi`, not `ollama ps`.
- Each model also uses ~0.6–0.9 GB of pinned host memory (shown as "shared GPU memory" in Task Manager). This is by design: part of Gemma's weights are kept in host memory.
- `qwen3.5:9b` (the planned fallback) was not needed and not tested.

## Token budgeting helper (spec for plan 09)

- **Tokenizer:** `tokenizer.json` from `google/gemma-4-12B-it`. Apache-2.0 and **not gated**; pin revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`. 32 MB, so download it on first use into `DATA_ROOT` (not into git or the image). Count with `tokenizers.Tokenizer.encode(text, add_special_tokens=False)`.
- **Verified:** on all 6 postings (1050–1494 tokens), the count was exactly Ollama's `prompt_eval_count` minus 1 (BOS) for a raw prompt.
- **Chat overhead:** add 10 tokens for the first message and 6 for each additional one (measured: 1 message → +9, 2 messages → +15).
- **Fallback** if the file cannot be loaded: 3.0 characters per token. Measured 3.57–3.69 for Danish and 4.77–5.50 for English, so 3.0 overestimates by ≥ 16%.
- **Writer budgets** at `num_ctx` 32768: architecture §5's 16k budgets doubled. System and instructions ≤ 2000, job brief ≤ 2000, CV evidence ≤ 8000, template or section ≤ 3000, output ≤ 4000 (19,000 total, ~13.7k headroom). Writers run with thinking off, so there is no thinking budget. The rubric's thinking cap (3072) is its output budget.
- The helper raises before a call that would exceed `num_ctx − output budget`, instead of letting Ollama truncate the prompt silently.
