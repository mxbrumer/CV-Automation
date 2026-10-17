# 14 — End-to-end test & v0.1.0 release

**Depends on:** all · **Branch:** `test/14-e2e`

## Goal
Prove the whole loop works from email to queue, harden operations, and cut the first release.

## Steps
1. **E2E script** `scripts/e2e.ps1`: fresh stack (`dev.ps1 reset-db`), import flows, seed profile with example CV/templates, point `JOBINDEX_FEEDS` at the fixture feed served locally (plan 07 fixtures; `ENV=dev` only), run the pipeline, approve one match through `POST /match-decision`, assert: 1 duplicate stopped, 1 low_match, 1 `match_declined`, 1 generated with all artifacts.
2. **Playwright** tests (`frontend/e2e/`): dashboard counts → matches (approve) → review → chat edit (Ollama mocked at backend via `ENV=test` stub) → approve → queue → submit → dashboard updated. Runs in CI with the stub; a real-LLM variant runs locally.
3. **Ops hardening:** `dev.ps1 backup` scheduled weekly (Windows Task Scheduler instructions in `docs/operations.md`); restore procedure tested once; log rotation for containers; restart policies `unless-stopped`.
4. **Docs pass:** README quick start (≤ 10 steps from clone to first run); check the README workflow diagram and `docs/assets/workflow.png` (plan 13) still match the code, and update the GitHub repo description (it still says "job-alert emails") with `gh repo edit --description` after the user approves the text; `docs/operations.md` (start/stop, backup/restore, updating models, updating LangFlow version and re-importing flows, where data lives).
5. **Security review:** run `/security-review`; confirm ports bound to 127.0.0.1, API key required, `.env` and profile untracked, Ollama not exposed on LAN.
6. **Release:** merge the pending release-please PR → `v0.1.0` tag, CHANGELOG, GHCR images, flows zip. Verify `docker compose` can run pinned `:0.1.0` images.
7. Review `docs/plans/README.md` Follow-ups with the user and propose the next plans.

## Acceptance criteria
- [x] `scripts/e2e.ps1` passes on a clean machine state (verified 2026-10-14).
- [x] Playwright suite green in CI (`e2e` job passed on PR #7, 2026-10-15).
- [x] GitHub Release `v0.1.0` exists with changelog and artifacts (released 2026-10-15 from PR #2; asset `langflow-flows-v0.1.0.zip`).
- [ ] ~~User has done one real run with their own Jobindex feeds and approved at least one application through both gates.~~ Waived 2026-10-17: superseded by plan 15 (manual intake replaces the Jobindex feed).
