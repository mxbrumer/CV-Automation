FROM python:3.12-slim

# WeasyPrint system libraries (used from plan 09 on) and curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 app
USER app
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8000

# Migrate, then serve. FastAPI owns the schema (architecture §4).
CMD ["sh", "-c", "alembic upgrade head && uvicorn ajs.main:app --host 0.0.0.0 --port 8000"]
