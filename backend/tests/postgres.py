"""Ephemeral PostgreSQL database support for the backend test suite."""

from __future__ import annotations

import atexit
import os
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel


ADMIN_URL = make_url(
    os.getenv(
        "TEST_POSTGRES_URL",
        "postgresql+psycopg://127.0.0.1:5432/postgres",
    )
).set(database="postgres")
ADMIN_ENGINE = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
TEST_DATABASE_NAME = f"audel_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
TEST_DATABASE_URL = ADMIN_URL.set(database=TEST_DATABASE_NAME)
TEST_ENGINE: Engine
_created_databases: set[str] = set()
_open_sessions: list[Session] = []
_cleaned_up = False


def _quoted_database(name: str) -> str:
    return ADMIN_ENGINE.dialect.identifier_preparer.quote(name)


def _create_database(name: str) -> None:
    with ADMIN_ENGINE.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {_quoted_database(name)}"))
    _created_databases.add(name)


def create_isolated_engine() -> Engine:
    name = f"{TEST_DATABASE_NAME}_{uuid.uuid4().hex[:8]}"
    _create_database(name)
    return create_engine(ADMIN_URL.set(database=name), pool_pre_ping=True)


def reset_database() -> None:
    with TEST_ENGINE.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    SQLModel.metadata.create_all(TEST_ENGINE)


def make_session() -> Session:
    session = Session(TEST_ENGINE)
    _open_sessions.append(session)
    return session


def close_test_sessions() -> None:
    while _open_sessions:
        session = _open_sessions.pop()
        session.rollback()
        session.close()


def seed_accounts(session: Session, count: int = 2) -> None:
    from app.budget.models import Account, PlaidItem

    item = PlaidItem(plaid_item_id="test-item", access_token="test-token")
    session.add(item)
    session.commit()
    session.refresh(item)
    for number in range(1, count + 1):
        session.add(
            Account(
                plaid_account_id=f"test-account-{number}",
                item_id=item.id,
                name=f"Test Account {number}",
                type="depository",
            )
        )
    session.commit()


def make_session_with_accounts(count: int = 2) -> Session:
    session = make_session()
    seed_accounts(session, count=count)
    return session


def cleanup_databases() -> None:
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True

    close_test_sessions()
    TEST_ENGINE.dispose()
    for name in list(_created_databases):
        with ADMIN_ENGINE.connect() as conn:
            conn.execute(
                text(f"DROP DATABASE IF EXISTS {_quoted_database(name)} WITH (FORCE)")
            )
        _created_databases.remove(name)
    ADMIN_ENGINE.dispose()


_create_database(TEST_DATABASE_NAME)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)
TEST_ENGINE = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
atexit.register(cleanup_databases)
