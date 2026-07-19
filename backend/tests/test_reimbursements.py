from datetime import date

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.models import Budget, Transaction
from app.budget.services.summary import build_summary


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _add(s, **kw):
    t = Transaction(account_id=1, **kw)
    s.add(t); s.commit(); s.refresh(t)
    return t


def _cat(out, category):
    return next((c["total"] for c in out["spending_by_category"] if c["category"] == category), None)


def test_spend_by_category_in_range_matches_monthly_summary():
    from app.budget.services.summary import build_summary, spend_by_category_in_range
    s = make_session()
    _add(s, date=date(2026, 7, 2), name="Groceries", amount=80.0, category="GROCERIES")
    dinner = _add(s, date=date(2026, 7, 12), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 14), name="Zelle from Ryan", amount=-60.0,
         category="TRANSFER_IN", reimburses_transaction_id=dinner.id)
    out = build_summary(s, "2026-07")
    by_month = {c["category"]: c["total"] for c in out["spending_by_category"]}
    ranged = spend_by_category_in_range(s, date(2026, 7, 1), date(2026, 7, 31))
    assert ranged == by_month  # reimbursement/rule-aware, same as the dashboard's month


def test_spend_by_category_in_range_windows_to_the_dates():
    from app.budget.services.summary import spend_by_category_in_range
    s = make_session()
    _add(s, date=date(2026, 7, 13), name="Lunch", amount=20.0, category="FOOD_AND_DRINK")   # this week
    _add(s, date=date(2026, 7, 5), name="OldLunch", amount=99.0, category="FOOD_AND_DRINK")  # prior week
    wk = spend_by_category_in_range(s, date(2026, 7, 12), date(2026, 7, 18))
    assert wk.get("FOOD_AND_DRINK") == 20.0


def test_linked_reimbursement_reduces_expense_category_and_totals():
    s = make_session()
    dinner = _add(s, date=date(2026, 7, 12), name="Group dinner", amount=180.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 14), name="Zelle payment from Ryan", amount=-60.0,
         category="TRANSFER_IN", reimburses_transaction_id=dinner.id)
    s.add(Budget(category="FOOD_AND_DRINK", monthly_limit=500.0)); s.commit()

    out = build_summary(s, "2026-07")
    assert _cat(out, "FOOD_AND_DRINK") == 120.0     # 180 − 60
    assert out["expense_total"] == 120.0
    assert out["income_total"] == 0.0               # the incoming Zelle is not income
    bp = next(b for b in out["budget_progress"] if b["category"] == "FOOD_AND_DRINK")
    assert bp["spent"] == 120.0
    assert bp["remaining"] == 380.0


def test_linked_reimbursement_nets_against_expense_month_not_zelle_month():
    s = make_session()
    dinner = _add(s, date=date(2026, 6, 12), name="Group dinner", amount=180.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 3), name="Zelle payment from Ryan", amount=-60.0,
         category="TRANSFER_IN", reimburses_transaction_id=dinner.id)

    june = build_summary(s, "2026-06")
    assert _cat(june, "FOOD_AND_DRINK") == 120.0
    assert june["expense_total"] == 120.0

    july = build_summary(s, "2026-07")
    assert july["expense_total"] == 0.0             # expense stayed in June
    assert july["income_total"] == 0.0              # Zelle isn't income in July either
    assert _cat(july, "FOOD_AND_DRINK") is None


def test_reimbursement_capped_at_expense_amount():
    s = make_session()
    lunch = _add(s, date=date(2026, 7, 2), name="Lunch", amount=50.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 3), name="Zelle payment from Sam", amount=-80.0,
         category="TRANSFER_IN", reimburses_transaction_id=lunch.id)

    out = build_summary(s, "2026-07")
    assert out["expense_total"] == 0.0              # capped: never below zero
    assert all(c["total"] >= 0 for c in out["spending_by_category"])


def test_multiple_reimbursements_sum_and_cap():
    s = make_session()
    dinner = _add(s, date=date(2026, 7, 2), name="Dinner", amount=180.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 3), name="Zelle from A", amount=-60.0,
         category="TRANSFER_IN", reimburses_transaction_id=dinner.id)
    _add(s, date=date(2026, 7, 4), name="Zelle from B", amount=-40.0,
         category="TRANSFER_IN", reimburses_transaction_id=dinner.id)

    out = build_summary(s, "2026-07")
    assert _cat(out, "FOOD_AND_DRINK") == 80.0      # 180 − (60 + 40)
    assert out["expense_total"] == 80.0


def test_category_only_reimbursement_reduces_category_in_zelle_month():
    s = make_session()
    _add(s, date=date(2026, 7, 2), name="Groceries", amount=100.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 9), name="Zelle payment from Mom", amount=-60.0,
         category="TRANSFER_IN", user_category="FOOD_AND_DRINK")  # category-only, no link

    out = build_summary(s, "2026-07")
    assert _cat(out, "FOOD_AND_DRINK") == 40.0      # 100 − 60
    assert out["expense_total"] == 40.0
    assert out["income_total"] == 0.0


def test_kept_incoming_zelle_only_nets_total_not_category():
    s = make_session()
    _add(s, date=date(2026, 7, 2), name="Groceries", amount=100.0, category="FOOD_AND_DRINK")
    _add(s, date=date(2026, 7, 9), name="Zelle payment from Mom", amount=-60.0,
         category="TRANSFER_IN", user_category="TRANSFER_IN")     # kept as a transfer

    out = build_summary(s, "2026-07")
    assert _cat(out, "FOOD_AND_DRINK") == 100.0     # category untouched
    assert out["expense_total"] == 40.0             # 100 − 60 netted globally only


def test_non_p2p_refund_still_counts_as_income():
    s = make_session()
    _add(s, date=date(2026, 7, 2), name="Store purchase", amount=100.0, category="GENERAL_MERCHANDISE")
    _add(s, date=date(2026, 7, 5), name="Refund from store", amount=-30.0, category="GENERAL_MERCHANDISE")

    out = build_summary(s, "2026-07")
    assert _cat(out, "GENERAL_MERCHANDISE") == 100.0  # refund does NOT reduce the category
    assert out["income_total"] == 30.0                # unchanged: still treated as income
