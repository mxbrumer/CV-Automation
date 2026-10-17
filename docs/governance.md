# Governance

Rules for this repo, where each is enforced, and how to change them. Everything runs locally; the
rules keep it that way.

| Rule | Enforced by |
|---|---|
| **Ollama is the only model endpoint.** No cloud LLM SDK, key or hosted-LLM URL in `backend/`, `langflow/` or `frontend/src`. | `scripts/governance_check.py` (rules `flows`, `sdk`; CI job `langflow` and `.pre-commit-config.yaml`). At runtime `ajs.services.egress` refuses any backend request to a hosted-LLM domain. The LangFlow container gets no model secrets. |
| **Every model component in a flow is Ollama-based**; base URLs and model names come from LangFlow variables (`OLLAMA_BASE_URL`, `LLM_AGENT_MODEL`, ...). | `governance_check.py` (`flows`) and `langflow/tests/test_flows_static.py`. |
| **Prompts change through a PR.** Every `langflow/prompts/*.md` body must be embedded verbatim in a flow. | `governance_check.py` (`prompts`). Edit the file, bump `version:`, rebuild the flow with its `langflow/tools/build_*.py`. |
| **No personal data in git** (CV, templates, `.eml`, `.env`, anything under `profile/`). | `governance_check.py` (`tracked`, reads `git ls-files`), `.gitignore`. |
| **The backend never reaches the public web** (D4: posting text is pasted, never fetched). Every httpx client is pinned to its one host: LangFlow, and Ollama for chat editing; Phoenix gets OTLP from the exporter. | `ajs.services.egress` (`only_hosts` is required), `governance_check.py` (rule `egress`: every `httpx.Client` in `backend/src` has event hooks and every `egress_hook` call passes `only_hosts`), and a backend test (`test_every_egress_hook_call_pins_its_hosts`). |
| **Traces are personal data.** They hold CV and posting text, so Phoenix stays on `127.0.0.1` and prunes after `PHOENIX_RETENTION_DAYS` (90). | `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` in `docker-compose.yml`; `scripts/dev.ps1 prune-traces` deletes on demand. |

Run the check yourself: `python scripts/governance_check.py` (standard library only). Its tests,
including a planted OpenAI component, are in `langflow/tests/test_governance_check.py`.

## Tracing

- **The backend** sends OpenTelemetry spans (FastAPI, httpx, SQLAlchemy) to Phoenix project `ajs-backend` (`OTEL_ENABLED=false` turns it off). Spans hold no bodies.
- **LangFlow** sends its own traces, one Phoenix project per flow (`analyze_and_match`, `generate_documents`; LangFlow names the project after the flow). It does not continue an incoming trace.
- **Link between the two:** every flow run gets a session id `ajs-<hex>`. The backend span `langflow.run` has it as `session.id`, `workflow_run.langflow_run_id` stores it, and the backend adds `ajs_session` and `ajs_trace_id` to the flow's JSON input, which LangFlow shows as `input.value` on the root span of its trace. `workflow_run.phoenix_trace_id` is the backend trace; `POST /workflow/run` returns both.
- Ollama and bge-m3 calls are plain `httpx` calls inside the custom components, so Phoenix shows component spans but no token counts (plan 08 note).

## Adding a model

Models are Ollama tags set in `infra/.env` (`LLM_AGENT_MODEL`, `LLM_WRITER_MODEL`, `EMBED_MODEL`) and passed to LangFlow as global variables by `scripts/import-flows.ps1`. To try another one: pull it with `scripts/pull-models.ps1`, benchmark it (`docs/model-evaluation.md`), record the experiment in Phoenix, then change the variable. Do not add a provider component or SDK: the governance check fails on it. Adding a new Ollama-based built-in component means adding its type to `ALLOWED_BUILTIN` in `scripts/governance_check.py` in the same PR.
