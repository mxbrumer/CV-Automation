# 11 — Frontend scaffold & dashboard

**Depends on:** 06 · **Branch:** `feat/11-frontend`

## Goal
React app shell with routing, typed API client, and the Home dashboard.

## Steps
1. `npm create vite@latest frontend -- --template react-ts`. Add: `react-router`, `@tanstack/react-query`, `openapi-typescript` + `openapi-fetch` (types from `backend/openapi.json`), a UI kit (recommend `shadcn/ui` + Tailwind; one choice, document it), `vitest` + `@testing-library/react`, `eslint`, `prettier`. Scripts: `dev`, `build`, `lint`, `typecheck`, `test`, `gen:api`. Version field carries the release-please marker (plan 02).
2. **Dev proxy:** Vite proxies `/api` → `http://127.0.0.1:8000` and injects `X-API-Key` from `frontend/.env.local` (gitignored). Production (nginx container) does the same via config template.
3. **Layout:** top nav with tabs **Home**, **Matches** (badge = count `awaiting_match_review`, D9), **Review** (badge = count `generated`), **Queue** (badge = count `approved`). Routes `/`, `/matches`, `/review`, `/review/:id`, `/queue`. The Matches content is built in plan 11b.
4. **Home dashboard** (brief): three stat tiles from `GET /api/v1/stats`:
   - Job postings reviewed (all non-duplicate rows)
   - Good matches (`match_score ≥ threshold`)
   - Applications submitted (`status = submitted`)
   Plus: small table of the last 10 postings (title, company, score, status), last pipeline run time/status, and a "Run pipeline now" button (`POST /workflow/run`). Optional: 30-day line of reviewed vs matched (load the `dataviz` skill before building any chart).
5. **Errors/empty states:** backend down → banner; zero data → friendly empty state.
6. **Dockerfile:** multi-stage node build → `nginx:alpine`; enable `frontend` service in compose.

## Acceptance criteria
- [ ] With seed data (plan 05), dashboard shows correct counts (component test with mocked API + manual check).
- [ ] `npm run lint && npm run typecheck && npm test -- --run && npm run build` pass; CI frontend job green.
- [ ] Works at 1280 px and 390 px widths.

## Out of scope
Review (12) and Queue (13) content, beyond route placeholders.
