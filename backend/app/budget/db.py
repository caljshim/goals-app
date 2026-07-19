from sqlmodel import Session, SQLModel, create_engine, select

from app.budget.categories import SPENDING_CATEGORIES
from app.config import get_settings
from app.budget.models import Budget, Category, GoalGroupSettings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


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


def ensure_schema(eng=engine) -> None:
    """Additive migrations for databases created before a column was added.
    SQLModel.metadata.create_all() creates missing tables but never alters existing
    ones, so an older money.db needs the new columns added by hand. Idempotent."""
    Budget.__table__.create(eng, checkfirst=True)
    GoalGroupSettings.__table__.create(eng, checkfirst=True)
    with eng.begin() as conn:
        # `Budget` moved to a period-aware table so one category can have daily,
        # weekly, and monthly guardrails. Copy the legacy monthly rows exactly once;
        # retain the old table as a recovery source.
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS appmigration (name VARCHAR PRIMARY KEY)"
        )
        legacy_budget = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='budget'"
        ).first()
        migrated = conn.exec_driver_sql(
            "SELECT name FROM appmigration WHERE name='period_budgets_v1'"
        ).first()
        if legacy_budget and not migrated:
            conn.exec_driver_sql(
                """
                INSERT INTO budgetrule (category, monthly_limit, period)
                SELECT category, monthly_limit, 'monthly' FROM budget
                WHERE NOT EXISTS (
                    SELECT 1 FROM budgetrule
                    WHERE budgetrule.category = budget.category
                      AND budgetrule.period = 'monthly'
                )
                """
            )
            conn.exec_driver_sql(
                "INSERT INTO appmigration (name) VALUES ('period_budgets_v1')"
            )
        cols = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("transaction")')}
        if cols and "reimburses_transaction_id" not in cols:
            conn.exec_driver_sql(
                'ALTER TABLE "transaction" ADD COLUMN reimburses_transaction_id INTEGER'
            )
        gcols = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("goal")')}
        if gcols and "period" not in gcols:
            conn.exec_driver_sql("ALTER TABLE \"goal\" ADD COLUMN period VARCHAR DEFAULT 'once'")
        if gcols and "period_anchor" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN period_anchor DATE')
        if gcols and "direction" not in gcols:
            conn.exec_driver_sql("ALTER TABLE \"goal\" ADD COLUMN direction VARCHAR DEFAULT 'reach'")
        if gcols and "step" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN step FLOAT DEFAULT 1.0')
        if gcols and "group" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN "group" VARCHAR')
        if gcols and "weekly_day" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN weekly_day VARCHAR')
        if gcols and "reset_time" not in gcols:
            conn.exec_driver_sql("ALTER TABLE \"goal\" ADD COLUMN reset_time VARCHAR DEFAULT '00:00'")
        if gcols and "weekly_reset_day" not in gcols:
            conn.exec_driver_sql("ALTER TABLE \"goal\" ADD COLUMN weekly_reset_day VARCHAR DEFAULT 'sunday'")
        if gcols and "monthly_reset_day" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN monthly_reset_day INTEGER DEFAULT 1')
        if gcols and "interval_days" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN interval_days INTEGER')
        if gcols and "archived_at" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN archived_at DATETIME')
        if gcols and "anchor_value" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN anchor_value FLOAT')
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
        if gcols and "financial_metric" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN financial_metric VARCHAR')
        if gcols and "financial_rule" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN financial_rule VARCHAR')
        if gcols and "financial_source" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN financial_source VARCHAR')
        if gcols and "icon" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN icon VARCHAR')
        if gcols and "color" not in gcols:
            conn.exec_driver_sql('ALTER TABLE "goal" ADD COLUMN color VARCHAR')

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
                "SELECT id FROM budgetrule WHERE category = ? AND period = ? AND id != ?",
                (normalized, row[2], row[0]),
            ).first()
            if not duplicate:
                conn.exec_driver_sql(
                    "UPDATE budgetrule SET category = ? WHERE id = ?", (normalized, row[0])
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
