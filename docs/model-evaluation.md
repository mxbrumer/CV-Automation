# Model evaluation (plan 04)

Measured on 2026-09-29/30 (Ollama 0.34.4) and **re-run on 2026-10-12 on Ollama 0.40.3** on the machine in [architecture.md §1](architecture.md#1-verified-environment-2026-09-28): RTX 5070 12 GB, Windows 11, native Ollama. Sections marked *(0.40.3)* are current; unmarked VRAM numbers are from 0.34.4 and were only spot-checked. Raw results and reports stay in `DATA_ROOT/evals/` and are not committed. This page holds only aggregates.

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
| JSON output | `format: <JSON schema>` (structured outputs), never `format: "json"` | Re-verified on 0.40.3: `format: "json"` + `think: false` gave 0/6 valid (extra text after the JSON, or the model's reasoning inside it); a schema gave 6/6. |
| Temperatures | agent 0.2 (extraction retried at 0.5 when the JSON is invalid), rubric 0.3, writer 0.7, set per request | The Modelfile sets none, so agent and writer calls share one loaded model. At 0.2, `job_brief` extraction of one Danish posting failed 3/3 with truncated JSON (the server stops with `done_reason: stop`, probably its token-repeat limit); at 0.5 and 0.8 it succeeded 4/4. |

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

Harness: [backend/evals/model_bench.py](../backend/evals/model_bench.py) (standalone uv script). Inputs: 6 real postings (3 Danish, 3 English) with hand-made labels (company, title, language, contact present). The rubric and writing tasks use the user's CV and templates. Tool and extraction ran 3 times per posting.

```powershell
uv run --system-certs backend/evals/model_bench.py run --tag r2 --rubric-temps 0.3
uv run backend/evals/model_bench.py score C:/dev/JobSearchData/evals/<date>-<tag>-ratings.csv
```

### Agent tasks *(0.40.3)*

6 postings (3 Danish, 3 English), 3 repeats. `job_brief` now also holds `location`, `relocation_ok`, `required_languages`, `danish_required` (D10).

| Model | `find_application` tool call correct | `job_brief` schema valid | Brief fields correct | Gen tok/s | Prompt tok/s |
|---|---|---|---|---|---|
| **ajs-gemma** (q8_0 KV, `num_ctx` 32768) | **18/18** | 15/18 | 60/60 of the valid ones | 63.5 | ~1550 |

- The 3 invalid extractions are one Danish posting at temperature 0.2 (see Decisions). Mimir and qwen2.5:14b were not re-run (D1 note, 2026-10-12); their 0.34.4 results stand: Mimir 0/18 on tools and JSON, qwen 18/18 and 18/18.
- "Correct" tool call: `find_application` called with the labelled company and title (normalized match).

### Rubric scoring: thinking off vs on *(0.40.3)*

Three criteria (skills, experience, domain; D10), each 0–5, total scaled to 0–100, temperature 0.3.

| Posting | Total off | Total on | Wall off | Wall on |
|---|---|---|---|---|
| DA-1 | 93 | invalid (cap) | 2.8 s | 129 s |
| DA-2 | 87 | 100 | 2.9 s | 27 s |
| DA-3 | 73 | 87 | 3.0 s | 21 s |
| EN-1 | 80 | 93 | 2.9 s | 13 s |
| EN-2 | 80 | 87 | 2.8 s | 16 s |
| EN-3 | 80 | invalid (cap) | 2.7 s | 129 s |

- Thinking off: 6/6 valid. Thinking on: 4/6 valid; the 2 failures are runaway thinking that hit the 8192-token cap in the harness (~130 s). Successful thinking calls used about 700–1700 tokens (2.7k–6.1k characters), so the 3072-token cap and the retry with thinking off (Decisions) still apply.
- Mean |off − on| is 11.8 points on the valid pairs and the criteria agree in 42% of cases; thinking on scores higher.
- **With only skills, experience and domain, every posting scores 73–100.** All of them are above the old threshold of 55, so the rubric alone does not separate postings. The D8 threshold is set from the user's would-apply labels (below).

### Writing tasks *(0.40.3)*

Always English (A2), filled from `cover_letter_template.md` / `recruiter_email_template.md`, thinking off, temperature 0.7.

| Task | Checks passed | Mean words |
|---|---|---|
| Cover letter (150–450 words, no `{{ }}` left) | 6/6 | 227 |
| Recruiter email (≤ 150 words, no `{{ }}` left) | 6/6 | 142 |

The blind 1–5 ratings (`DATA_ROOT/evals/2026-10-12-r2-ratings.csv`) are pending. The automated checks do not judge quality or invented facts.

### Co-residency *(0.40.3)*

- `/api/ps` showed both models fully on GPU in 11/12 checks after postings. The miss is the first load: Gemma loaded after `bge-m3` evicts it. Controlled test: `bge-m3` then Gemma leaves **only Gemma**; Gemma then `bge-m3` leaves **both**, 100% GPU. Same behaviour as 0.34.4, so the worker still warms up `ajs-gemma` first.
- Peak `nvidia-smi` memory.used: 10,747 MiB of 12,227 MiB.

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
