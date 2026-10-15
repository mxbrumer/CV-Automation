"""API test fixtures. Need DATABASE_URL pointing at a scratch Postgres (see test_migrations)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from ajs.db.session import get_session
from ajs.main import app
from ajs.settings import Settings, get_settings

BACKEND = Path(__file__).resolve().parent.parent
API_KEY = "test-key"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        pytest.skip("DATABASE_URL not set")
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session inside an outer transaction that is rolled back after each test."""
    with engine.connect() as conn:
        outer = conn.begin()
        session = Session(conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        yield session
        session.close()
        outer.rollback()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_root = tmp_path / "data"
    (data_root / "profile").mkdir(parents=True)
    (data_root / "applications").mkdir()
    return Settings(data_root=data_root, backend_api_key=API_KEY, match_threshold=55)


@pytest.fixture
def client(db: Session, settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c
    app.dependency_overrides.clear()
