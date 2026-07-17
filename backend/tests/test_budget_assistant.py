from datetime import date
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.budget.db import seed_default_categories
from app.budget.models import Budget, Category, Transaction
from app.budget.services import assistant


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    s = Session(eng)
    seed_default_categories(s)  # mirror init_db: DB is the category source of truth
    return s


def seed(s):
    months = assistant._prev_complete_months(assistant.AVG_MONTHS)
    y, m = (int(x) for x in months[0].split("-"))
    d = date(y, m, 15)
    s.add(Transaction(account_id=1, date=d, name="Panda Express", merchant_name="Panda Express",
                      amount=30.0, category="FOOD_AND_DRINK"))
    s.add(Transaction(account_id=1, date=d, name="Safeway", merchant_name="Safeway",
                      amount=90.0, category="GROCERIES"))
    s.add(Transaction(account_id=1, date=d, name="Paycheck", amount=-3000.0, category="INCOME"))
    # transfer — must be excluded from overview/lists
    s.add(Transaction(account_id=1, date=d, name="Payment to Chase", amount=500.0, category="LOAN_PAYMENTS"))
    s.commit()


def test_overview_excludes_transfers_and_averages():
    s = make_session(); seed(s)
    data, action = assistant._overview(s)
    assert action is None
    cats = {c["category"] for c in data["avg_monthly_by_category"]}
    assert "LOAN_PAYMENTS" not in cats
    assert "FOOD_AND_DRINK" in cats
    assert data["avg_monthly_income"] == round(3000.0 / assistant.AVG_MONTHS, 2)
    # canonical spending buckets are passed so the model reuses them
    assert "FOOD_AND_DRINK" in data["known_categories"]
    assert "TRANSPORTATION" in data["known_categories"]
    assert "LOAN_PAYMENTS" not in data["known_categories"]
    assert "INCOME" not in data["known_categories"]


def test_overview_averages_only_full_data_months():
    # Data starts mid-month, so the earliest calendar month is partial and must be
    # excluded from the average (else it drags per-month figures down).
    s = make_session()
    months = assistant._prev_complete_months(3)  # most-recent first: [newest, middle, oldest]
    newest, oldest = months[0], months[-1]
    ny, nm = int(newest[:4]), int(newest[5:7])
    oy, om = int(oldest[:4]), int(oldest[5:7])
    # partial oldest month (data begins on the 20th)
    s.add(Transaction(account_id=1, date=date(oy, om, 20), name="p", amount=900.0, category="FOOD_AND_DRINK"))
    # full newest month
    s.add(Transaction(account_id=1, date=date(ny, nm, 10), name="q", amount=3000.0, category="FOOD_AND_DRINK"))
    s.add(Transaction(account_id=1, date=date(ny, nm, 11), name="pay", amount=-4000.0, category="INCOME"))
    s.commit()

    data, _ = assistant._overview(s)
    assert oldest not in data["window_months"]      # partial month dropped
    assert newest in data["window_months"]
    assert data["months_averaged"] == len(data["window_months"]) == 2  # middle + newest
    food = next(c for c in data["avg_monthly_by_category"] if c["category"] == "FOOD_AND_DRINK")
    assert food["avg_monthly"] == round(3000.0 / 2, 2)   # April's 900 excluded
    assert data["avg_monthly_income"] == round(4000.0 / 2, 2)


def test_list_transactions_excludes_transfers():
    s = make_session(); seed(s)
    data, _ = assistant._list_transactions(s)
    names = {t["name"] for t in data["transactions"]}
    assert "Payment to Chase" not in names
    assert "Panda Express" in names


def test_set_budget_upserts_and_normalizes():
    s = make_session()
    data, action = assistant._set_budget(s, "food and drink", 300)
    assert data["category"] == "FOOD_AND_DRINK" and data["created"] is True
    assert "FOOD_AND_DRINK" in action
    data2, _ = assistant._set_budget(s, "FOOD_AND_DRINK", 250)
    assert data2["created"] is False
    budgets = s.exec(select(Budget)).all()
    assert len(budgets) == 1 and budgets[0].monthly_limit == 250


def test_recategorize_sets_user_category_and_registers_it():
    s = make_session(); seed(s)
    t = s.exec(select(Transaction).where(Transaction.name == "Panda Express")).first()
    data, action = assistant._recategorize(s, [t.id], "dining out")
    assert data["updated"] == 1 and data["category"] == "DINING_OUT"
    s.refresh(t)
    assert t.user_category == "DINING_OUT"
    # a brand-new category is persisted to the category table
    assert "DINING_OUT" in {c.name for c in s.exec(select(Category)).all()}


def test_delete_budget_removes_row_and_reports():
    s = make_session()
    assistant._set_budget(s, "FOOD_AND_DRINK", 300)
    data, action = assistant._delete_budget(s, "food and drink")
    assert data == {"category": "FOOD_AND_DRINK", "deleted": True}
    assert action == "Deleted budget FOOD_AND_DRINK"
    assert s.exec(select(Budget)).all() == []
    # deleting a missing budget reports an error the model can relay
    data2, action2 = assistant._delete_budget(s, "TRAVEL")
    assert "no budget" in data2["error"] and action2 is None


def test_recategorize_refuses_credit_card_payments():
    # The assistant once stamped GROCERIES onto card payments, double-counting them
    # as spending. Payment legs must be immune to recategorization.
    s = make_session()
    months = assistant._prev_complete_months(1)
    y, m = int(months[0][:4]), int(months[0][5:7])
    s.add(Transaction(account_id=1, date=date(y, m, 10), name="Payment to Chase card ending in 8841",
                      amount=500.0, category="LOAN_PAYMENTS"))
    s.commit()
    t = s.exec(select(Transaction)).first()

    data, action = assistant._recategorize(s, [t.id], "GROCERIES")
    assert data["updated"] == 0
    assert t.id in data["skipped_payment_ids"]
    s.refresh(t)
    assert t.user_category is None  # untouched


def test_overview_spend_includes_p2p_net():
    s = make_session()
    months = assistant._prev_complete_months(assistant.AVG_MONTHS)
    y, m = int(months[0][:4]), int(months[0][5:7])
    d = date(y, m, 10)
    s.add(Transaction(account_id=1, date=d, name="Safeway", amount=300.0, category="GENERAL_MERCHANDISE"))
    s.add(Transaction(account_id=1, date=d, name="Zelle payment from LUCAS KIM", amount=-90.0, category="TRANSFER_IN"))
    s.add(Transaction(account_id=1, date=d, name="Venmo", amount=30.0, category="TRANSFER_OUT"))
    s.add(Transaction(account_id=1, date=d, name="Online Transfer from CHK", amount=-500.0, category="TRANSFER_IN"))
    s.commit()

    data, _ = assistant._overview(s)
    n = data["months_averaged"]
    # gross 300, −90 reimbursed, +30 paid out; own-account transfer ignored
    assert data["avg_monthly_spend_total"] == round((300.0 - 90.0 + 30.0) / n, 2)
    assert data["avg_monthly_p2p_net"] == round((-90.0 + 30.0) / n, 2)


def test_add_category_persists():
    s = make_session()
    data, action = assistant._add_category(s, "gifts & donations")
    assert data == {"category": "GIFTS_&_DONATIONS", "created": True}
    assert "GIFTS_&_DONATIONS" in {c.name for c in s.exec(select(Category)).all()}
    # idempotent
    data2, _ = assistant._add_category(s, "GIFTS_&_DONATIONS")
    assert data2["created"] is False


class _FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_run_assistant_applies_tool_then_replies():
    s = make_session(); seed(s)
    tool_block = SimpleNamespace(type="tool_use", id="tu_1", name="set_budget",
                                 input={"category": "FOOD_AND_DRINK", "monthly_limit": 200})
    text_block = SimpleNamespace(type="text", text="Done — set your dining budget to $200.")
    client = _FakeClient([
        _FakeResp("tool_use", [tool_block]),
        _FakeResp("end_turn", [text_block]),
    ])

    result = assistant.run_assistant(
        s, [{"role": "user", "content": "Set my food budget to 200"}], client=client,
    )

    assert result["refresh"] is True
    assert any("FOOD_AND_DRINK" in a for a in result["actions"])
    assert "200" in result["reply"]
    b = s.exec(select(Budget).where(Budget.category == "FOOD_AND_DRINK")).first()
    assert b is not None and b.monthly_limit == 200
    assert len(client.messages.calls) == 2  # tool round-trip + final reply
