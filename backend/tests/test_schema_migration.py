from datetime import date

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.db import ensure_schema
from app.budget.models import Transaction


def test_transaction_stores_reimburses_link():
    """An incoming Zelle can point at the expense it reimburses."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        expense = Transaction(account_id=1, date=date(2026, 7, 1), name="Dinner",
                              amount=180.0, category="FOOD_AND_DRINK")
        s.add(expense); s.commit(); s.refresh(expense)
        zelle = Transaction(account_id=1, date=date(2026, 7, 2), name="Zelle from Ryan",
                            amount=-60.0, category="TRANSFER_IN",
                            reimburses_transaction_id=expense.id)
        s.add(zelle); s.commit(); s.refresh(zelle)
        assert zelle.reimburses_transaction_id == expense.id


def test_ensure_schema_adds_reimburses_column_to_old_db(tmp_path):
    """create_all() won't alter an existing table, so ensure_schema() must add the
    new column to a database created before this feature — without touching data."""
    db = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{db}")
    # Simulate a pre-feature database: the transaction table without the new column.
    with eng.begin() as conn:
        conn.exec_driver_sql(
            'CREATE TABLE "transaction" ('
            "id INTEGER PRIMARY KEY, plaid_transaction_id VARCHAR, account_id INTEGER NOT NULL, "
            "date DATE NOT NULL, name VARCHAR NOT NULL, merchant_name VARCHAR, "
            "amount FLOAT NOT NULL, category VARCHAR, user_category VARCHAR, pending BOOLEAN NOT NULL)"
        )
        conn.exec_driver_sql(
            'INSERT INTO "transaction" (account_id, date, name, amount, pending) '
            "VALUES (1, '2026-07-01', 'Old', 5.0, 0)"
        )

    ensure_schema(eng)

    with eng.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("transaction")')}
        assert "reimburses_transaction_id" in cols
        row = conn.exec_driver_sql(
            'SELECT name, reimburses_transaction_id FROM "transaction"'
        ).one()
        assert row[0] == "Old"        # existing data preserved
        assert row[1] is None         # new column defaults to NULL


def test_ensure_schema_is_idempotent(tmp_path):
    """Running the migration when the column already exists is a no-op, not an error."""
    db = tmp_path / "new.db"
    eng = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(eng)  # already has the column
    ensure_schema(eng)
    ensure_schema(eng)  # second run must not raise
