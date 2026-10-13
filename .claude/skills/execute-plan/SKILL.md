---
name: execute-plan
description: Execute an implementation plan from docs/plans/ (a given number like "03", or the next runnable one). Use when the user says "execute plan N", "next plan", or invokes /execute-plan.
---

# Execute a plan

Argument: optional plan number (e.g. `03`). Without it, pick the next plan.

1. Read `docs/plans/README.md` and `docs/architecture.md`. Decisions D1–D11 and assumptions A1–A6 are fixed; if one proves wrong, stop and ask the user.
2. Choose the plan:
   - If a number was given, use it. If any of its dependencies is not `done`, tell the user and stop.
   - Otherwise take the lowest-numbered plan with status `todo` whose dependencies are all `done`.
3. Set its status to `in progress` in the README table.
4. Read the plan file and its "Read first" links, then execute the Steps in order on branch `feat/NN-short-name` (unless the plan names another branch). Use Conventional Commits.
5. Stay in scope. Append out-of-scope discoveries under **Follow-ups** in `docs/plans/README.md`.
6. Verify every acceptance criterion by running the listed commands. Do not tick a box you did not verify; report failures plainly.
7. When all criteria pass, set the status to `done`, commit, and summarise what was done, what was verified, and any follow-ups.

Never commit personal data (CV, templates, emails, `.env`) and never add cloud LLM SDKs or keys.
