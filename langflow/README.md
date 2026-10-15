# LangFlow flows

| Path | What |
|---|---|
| `flows/<name>.json` | Exported flows (stable key order, no secrets). `analyze_and_match` is brief steps 2-10. |
| `components/ajs/*.py` | Custom components, mounted read-only at `LANGFLOW_COMPONENTS_PATH`. Each is self-contained because the flow embeds the component source. |
| `prompts/*.md`, `prompts/schemas/` | Reviewable mirror of every prompt and JSON schema in the flows (version header). The build script embeds them; `tests/test_flows_static.py` checks they match. |
| `tools/` | `normalize_flow.py` (used by the export) and `build_analyze_and_match.py` (regenerates the flow from the files above). |
| `tests/` | Static checks (CI) and golden tests (`@pytest.mark.llm`, local only). |

## Workflow

```powershell
scripts/dev.ps1 up
scripts/import-flows.ps1                       # global variables + flows into a fresh LangFlow
scripts/export-flows.ps1 [-Name analyze_and_match]   # after editing in the UI
```

After editing a component file or a prompt: restart LangFlow (`docker compose -f infra/docker-compose.yml restart langflow`), run `python langflow/tools/build_analyze_and_match.py`, then `scripts/export-flows.ps1 -Name analyze_and_match`.

Global variables (created by `import-flows.ps1` from `infra/.env`): `OLLAMA_BASE_URL`, `LLM_AGENT_MODEL`, `LLM_WRITER_MODEL`, `EMBED_MODEL`, `LLM_KEEP_ALIVE`, `BACKEND_URL`, `BACKEND_API_KEY`.

The backend starts a run with `POST /api/v1/run/analyze_and_match` (the endpoint name survives re-imports) and the input `{"posting_id": 12}`.

## Tests

```powershell
cd backend
uv run --with jsonschema pytest ../langflow/tests -c ../langflow/tests/pytest.ini --rootdir ../langflow/tests -m "not llm"   # static
uv run --with jsonschema pytest ../langflow/tests -c ../langflow/tests/pytest.ini --rootdir ../langflow/tests -m llm         # golden, about 4 minutes
```

The golden tests need the running stack, native Ollama and `cv.md` in `DATA_ROOT/profile`. They add postings with source `golden-test` to the app database (clear with `scripts/dev.ps1 reset-db`). Set `MATCH_THRESHOLD` in the shell if it differs from the backend's.
