import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DATA_ROOT, backendEnv } from './env.ts'

// Migrate the scratch database and reseed the fake postings (one per status) with draft files,
// so every run starts from the same state. Needs `uv sync` done in ../backend.
export default function globalSetup() {
  fs.rmSync(DATA_ROOT, { recursive: true, force: true })
  for (const dir of ['applications', 'profile']) {
    fs.mkdirSync(path.join(DATA_ROOT, dir), { recursive: true })
  }
  const cwd = fileURLToPath(new URL('../../backend', import.meta.url))
  const run = (...args: string[]) =>
    execFileSync('uv', ['run', ...args], {
      cwd,
      env: { ...process.env, ...backendEnv },
      stdio: 'inherit',
      shell: process.platform === 'win32',
    })
  run('alembic', 'upgrade', 'head')
  run('python', 'scripts/seed_dev.py', '--reset', '--files')
}
