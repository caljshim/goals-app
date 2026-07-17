from datetime import date

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.budget.models import Budget, Transaction
from app.budget.services.summary import build_summary


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def seed(s):
    s.add(Transaction(account_id=1, date=date(2026, 7, 2), name="Groceries", amount=80.0, category="GROCERIES"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 5), name="Rent", amount=1200.0, category="RENT"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 6), name="Paycheck", amount=-2000.0, category="INCOME"))
    s.add(Transaction(account_id=1, date=date(2026, 6, 10), name="OldGroceries", amount=50.0, category="GROCERIES"))
    s.add(Budget(category="GROCERIES", monthly_limit=300.0))
    s.commit()


def test_summary_totals_and_categories():
    s = make_session(); seed(s)
    out = build_summary(s, "2026-07")
    assert out["expense_total"] == 1280.0
    assert out["income_total"] == 2000.0
    assert out["net"] == 720.0
    top = out["spending_by_category"][0]
    assert top == {"category": "RENT", "total": 1200.0}


def test_budget_progress_uses_effective_category():
    s = make_session(); seed(s)
    out = build_summary(s, "2026-07")
    groceries = next(b for b in out["budget_progress"] if b["category"] == "GROCERIES")
    assert groceries["spent"] == 80.0
    assert groceries["limit"] == 300.0
    assert groceries["remaining"] == 220.0


def test_complete_months_excludes_partial_leading_and_current_month():
    s = make_session()
    # data begins mid-April → April is partial; May and June are full months
    s.add(Transaction(account_id=1, date=date(2026, 4, 20), name="a", amount=100.0, category="X"))
    s.add(Transaction(account_id=1, date=date(2026, 5, 5), name="b", amount=100.0, category="X"))
    s.add(Transaction(account_id=1, date=date(2026, 6, 5), name="c", amount=100.0, category="X"))
    s.commit()
    out = build_summary(s, "2026-07")
    assert out["complete_months"] == ["2026-05", "2026-06"]  # April partial, July current — both excluded


def test_transfers_excluded_from_spending_and_income():
    s = make_session(); seed(s)
    # A credit-card payment shows up twice: leaving checking (LOAN_PAYMENTS, +) and
    # as a credit on the card (LOAN_DISBURSEMENTS, -). Plus a Zelle transfer pair.
    s.add(Transaction(account_id=1, date=date(2026, 7, 10), name="Payment to Chase card ending in 8841",
                      amount=1456.21, category="LOAN_PAYMENTS"))
    s.add(Transaction(account_id=2, date=date(2026, 7, 10), name="Payment Thank You-Mobile",
                      amount=-1456.21, category="LOAN_DISBURSEMENTS"))
    # own-account moves (non-P2P) — must stay fully excluded
    s.add(Transaction(account_id=1, date=date(2026, 7, 12), name="Online Transfer to Savings", amount=45.0, category="TRANSFER_OUT"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 12), name="Online Transfer from CHK ...4883", amount=-60.0, category="TRANSFER_IN"))
    s.commit()

    out = build_summary(s, "2026-07")
    # Transfers move money between accounts; they must not shift spending or income.
    assert out["expense_total"] == 1280.0
    assert out["income_total"] == 2000.0
    assert out["net"] == 720.0
    cats = {c["category"] for c in out["spending_by_category"]}
    assert cats.isdisjoint({"LOAN_PAYMENTS", "LOAN_DISBURSEMENTS", "TRANSFER_IN", "TRANSFER_OUT"})
    july = next(m for m in out["monthly_trend"] if m["month"] == "2026-07")
    assert july["expense"] == 1280.0
    assert july["income"] == 2000.0


def test_p2p_zelle_venmo_adjusts_spending_but_own_transfers_do_not():
    s = make_session(); seed(s)
    # Reimbursements in (−), paying friends out (+), and an own-account transfer.
    s.add(Transaction(account_id=1, date=date(2026, 7, 8), name="Zelle payment from RYAN UYEKI BAC1",
                      amount=-60.0, category="TRANSFER_IN"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 9), name="Venmo", amount=25.0, category="TRANSFER_OUT"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 10), name="Online Transfer from CHK ...4883",
                      amount=-300.0, category="TRANSFER_IN"))
    s.commit()

    out = build_summary(s, "2026-07")
    # base spending 1280, minus $60 reimbursement, plus $25 paid to a friend
    assert out["expense_total"] == 1280.0 - 60.0 + 25.0
    assert out["income_total"] == 2000.0            # paycheck only; transfers never income
    july = next(m for m in out["monthly_trend"] if m["month"] == "2026-07")
    assert july["expense"] == 1280.0 - 60.0 + 25.0
    # P2P stays out of the category pie (can't attribute a reimbursement to a category)
    cats = {c["category"] for c in out["spending_by_category"]}
    assert cats.isdisjoint({"TRANSFER_IN", "TRANSFER_OUT"})


def test_monthly_trend_has_six_months_ending_at_month():
    s = make_session(); seed(s)
    out = build_summary(s, "2026-07")
    months = [m["month"] for m in out["monthly_trend"]]
    assert months == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    june = next(m for m in out["monthly_trend"] if m["month"] == "2026-06")
    assert june["expense"] == 50.0
