import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.postgres import (
    TEST_ENGINE,
    close_test_sessions,
    cleanup_databases,
    create_isolated_engine,
    reset_database,
)
from app.budget.db import get_session
from app.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def isolate_backend(monkeypatch):
    """Give every test a clean PostgreSQL schema and no local tunnel key."""
    monkeypatch.setenv("APP_API_KEY", "")
    get_settings.cache_clear()
    reset_database()
    try:
        yield
    finally:
        close_test_sessions()
        get_settings.cache_clear()


@pytest.fixture
def engine():
    return TEST_ENGINE


@pytest.fixture
def postgres_engine_factory():
    engines = []

    def factory():
        eng = create_isolated_engine()
        engines.append(eng)
        return eng

    yield factory
    for eng in engines:
        eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def pytest_sessionfinish(session, exitstatus):
    cleanup_databases()
