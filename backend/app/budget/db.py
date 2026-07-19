from sqlmodel import Session, SQLModel, create_engine, select

from app.budget.categories import SPENDING_CATEGORIES
from app.config import get_settings
from app.budget.models import Category

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
    with eng.begin() as conn:
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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_schema(engine)
    with Session(engine) as session:
        seed_default_categories(session)


def get_session():
    with Session(engine) as session:
        yield session
