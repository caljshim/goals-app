from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url
from sqlmodel import Session, SQLModel, create_engine, select

from app.budget.categories import SPENDING_CATEGORIES
from app.config import get_settings
from app.budget.models import (
    AgentJob,
    Budget,
    CalendarEvent,
    Category,
    GoalGroupSettings,
    Reminder,
)

settings = get_settings()
database_url = make_url(settings.database_url)
if database_url.get_backend_name() != "postgresql":
    raise RuntimeError(
        "DATABASE_URL must point to PostgreSQL "
        "(for example postgresql+psycopg://127.0.0.1:5432/audel)"
    )
engine = create_engine(settings.database_url, pool_pre_ping=True)


def seed_default_categories(session: Session) -> None:
    """Idempotently populate the category table with the default spending buckets."""
    existing = {c.name for c in session.exec(select(Category)).all()}
    added = False
    for name in sorted(SPENDING_CATEGORIES):
        if name not in existing:
            session.add(Category(name=name))
            added = True
    if added:
        session.commit()


def _column_names(conn: Connection, table_name: str) -> set[str]:
    inspector = inspect(conn)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_missing_columns(
    conn: Connection,
    table_name: str,
    definitions: dict[str, str],
) -> set[str]:
    if not inspect(conn).has_table(table_name):
        return set()
    columns = _column_names(conn, table_name)
    for column_name, definition in definitions.items():
        if column_name not in columns:
            conn.exec_driver_sql(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
            )
            columns.add(column_name)
    return columns


def ensure_schema(eng: Engine = engine) -> None:
    """Apply the small, additive migrations that predate a formal migration tool.

    SQLModel creates missing tables but does not alter existing ones. These
    migrations intentionally use PostgreSQL metadata and SQL.
    """
    Budget.__table__.create(eng, checkfirst=True)
    GoalGroupSettings.__table__.create(eng, checkfirst=True)
    Reminder.__table__.create(eng, checkfirst=True)
    CalendarEvent.__table__.create(eng, checkfirst=True)
    AgentJob.__table__.create(eng, checkfirst=True)
    with eng.begin() as conn:
        transaction_columns = _add_missing_columns(
            conn,
            "transaction",
            {
                "reimburses_transaction_id": (
                    'INTEGER REFERENCES "transaction"(id) ON DELETE SET NULL'
                )
            },
        )
        if "reimburses_transaction_id" in transaction_columns:
            conn.exec_driver_sql(
                'CREATE INDEX IF NOT EXISTS ix_transaction_reimburses_transaction_id '
                'ON "transaction" (reimburses_transaction_id)'
            )

        _add_missing_columns(
            conn,
            "plaiditem",
            {"reconciliation_version": "INTEGER DEFAULT 0"},
        )
        account_columns = _add_missing_columns(
            conn,
            "account",
            {"persistent_account_id": "VARCHAR"},
        )
        if "persistent_account_id" in account_columns:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_account_persistent_account_id "
                "ON account (persistent_account_id)"
            )

        original_goal_columns = _column_names(conn, "goal")
        gcols = _add_missing_columns(
            conn,
            "goal",
            {
                "period": "VARCHAR DEFAULT 'once'",
                "period_anchor": "DATE",
                "direction": "VARCHAR DEFAULT 'reach'",
                "step": "DOUBLE PRECISION DEFAULT 1.0",
                "group": "VARCHAR",
                "weekly_day": "VARCHAR",
                "reminder_time": "VARCHAR",
                "repeat_until_completed": "BOOLEAN DEFAULT FALSE",
                "nudge_interval_minutes": "INTEGER",
                "reset_time": "VARCHAR DEFAULT '00:00'",
                "weekly_reset_day": "VARCHAR DEFAULT 'sunday'",
                "monthly_reset_day": "INTEGER DEFAULT 1",
                "interval_days": "INTEGER",
                "archived_at": "TIMESTAMP",
                "anchor_value": "DOUBLE PRECISION",
                "financial_metric": "VARCHAR",
                "financial_rule": "VARCHAR",
                "financial_source": "VARCHAR",
                "icon": "VARCHAR",
                "color": "VARCHAR",
                "important": "BOOLEAN DEFAULT FALSE",
            },
        )
        if gcols and "anchor_value" not in original_goal_columns:
            # Older under-goals already have their initial manual value in history.
            # Fall back to the stored current value only when no history exists.
            conn.exec_driver_sql(
                """
                UPDATE goal
                SET anchor_value = COALESCE(
                    (SELECT value FROM goalhistory
                     WHERE goalhistory.goal_id = goal.id
                     ORDER BY goalhistory.id LIMIT 1),
                    current
                )
                WHERE direction = 'under' AND anchor_value IS NULL
                """
            )

        _add_missing_columns(
            conn,
            "reminder",
            {
                "repeat_until_completed": "BOOLEAN DEFAULT FALSE",
                "nudge_interval_minutes": "INTEGER",
                "important": "BOOLEAN DEFAULT FALSE",
                "repeat_rule": "VARCHAR DEFAULT 'none'",
            },
        )

        # Auto-integration proposals were introduced before the exact web-search
        # result URLs were retained separately from model-authored evidence.
        _add_missing_columns(
            conn,
            "integration_proposal",
            {
                "research_sources_json": (
                    "JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
            },
        )

        # Spending limits used to be represented as goals. Convert active rows to
        # budget rules, then archive them so their history remains recoverable.
        if gcols and {"kind", "category", "target", "period", "archived_at"}.issubset(gcols):
            conn.exec_driver_sql(
                """
                INSERT INTO budgetrule (category, monthly_limit, period)
                SELECT UPPER(REPLACE(TRIM(category), ' ', '_')), target,
                       CASE WHEN period IN ('daily', 'weekly', 'monthly') THEN period ELSE 'monthly' END
                FROM goal
                WHERE archived_at IS NULL AND category IS NOT NULL AND target > 0
                  AND (kind = 'spend_cap' OR (kind = 'financial' AND financial_metric = 'category_spend'))
                  AND NOT EXISTS (
                    SELECT 1 FROM budgetrule
                    WHERE budgetrule.category = UPPER(REPLACE(TRIM(goal.category), ' ', '_'))
                      AND budgetrule.period = CASE
                          WHEN goal.period IN ('daily', 'weekly', 'monthly') THEN goal.period
                          ELSE 'monthly' END
                  )
                """
            )
            conn.exec_driver_sql(
                """
                UPDATE goal SET archived_at = CURRENT_TIMESTAMP
                WHERE archived_at IS NULL
                  AND (kind = 'spend_cap' OR (kind = 'financial' AND financial_metric = 'category_spend'))
                """
            )

        # Normalize older free-form budget labels when doing so cannot collide
        # with another rule for the same period.
        for row in conn.exec_driver_sql(
            "SELECT id, category, period FROM budgetrule"
        ).all():
            normalized = "_".join(str(row[1]).strip().upper().split())
            if not normalized or normalized == row[1]:
                continue
            duplicate = conn.exec_driver_sql(
                "SELECT id FROM budgetrule "
                "WHERE category = %(category)s AND period = %(period)s AND id != %(id)s",
                {"category": normalized, "period": row[2], "id": row[0]},
            ).first()
            if not duplicate:
                conn.exec_driver_sql(
                    "UPDATE budgetrule SET category = %(category)s WHERE id = %(id)s",
                    {"category": normalized, "id": row[0]},
                )


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_schema(engine)
    with Session(engine) as session:
        seed_default_categories(session)
        # Give existing account-linked savings goals a first chart point using
        # the most recently stored balance; later bank syncs update it daily.
        from app.budget.services.goals import record_financial_goal_snapshots
        record_financial_goal_snapshots(session)


def get_session():
    with Session(engine) as session:
        yield session
