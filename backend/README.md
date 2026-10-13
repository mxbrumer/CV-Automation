# AI Job Search backend

FastAPI service and owner of the Postgres schema (Alembic). See `docs/architecture.md`.

- Tests: `uv run pytest` (needs `DATABASE_URL` pointing at an empty scratch database)
- Migrations: `uv run alembic upgrade head`
- Dev data: `uv run python scripts/seed_dev.py`
