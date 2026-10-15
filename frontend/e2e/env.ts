// Shared by playwright.config.ts and global-setup.ts: one throwaway backend on its own ports,
// database and data folder, so it never touches the real stack (ports 8000 / 5173).
import os from 'node:os'
import path from 'node:path'

export const BACKEND_PORT = 8100
export const WEB_PORT = 5199
export const API_KEY = 'e2e-key'

// A scratch Postgres database. Locally: the compose Postgres with a `jobsearch_scratch` role
// (see docs/plans/README.md, plan 05 note). In CI: the service container of the e2e job.
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ??
  'postgresql+psycopg://jobsearch_scratch:jobsearch@127.0.0.1:5432/jobsearch_e2e'

export const DATA_ROOT = path.join(os.tmpdir(), 'ajs-e2e-data')

// E2E_REAL_LLM=1 leaves ENV unset so the chat talks to the local Ollama instead of the stub.
export const REAL_LLM = process.env.E2E_REAL_LLM === '1'

export const backendEnv: Record<string, string> = {
  ...(REAL_LLM ? {} : { ENV: 'test' }),
  DATABASE_URL,
  DATA_ROOT,
  BACKEND_API_KEY: API_KEY,
  OTEL_ENABLED: 'false',
  // The backend runs on the host here, not in Docker. Ollama is reached directly; LangFlow is
  // pointed at an unused port so a test run can never reach the real stack's flows.
  OLLAMA_BASE_URL: 'http://127.0.0.1:11434',
  LANGFLOW_URL: 'http://127.0.0.1:9',
}
