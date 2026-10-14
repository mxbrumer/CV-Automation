import { defineConfig, devices } from '@playwright/test'
import { API_KEY, BACKEND_PORT, WEB_PORT, backendEnv } from './e2e/env.ts'

// Browser e2e (plan 14). Starts its own backend (ENV=test: stubbed chat, no LangFlow) and the Vite
// dev server on spare ports. `npm run test:e2e`; set E2E_REAL_LLM=1 for the local Ollama variant.
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  timeout: process.env.E2E_REAL_LLM === '1' ? 600_000 : 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `uv run uvicorn ajs.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}`,
        BACKEND_API_KEY: API_KEY,
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
