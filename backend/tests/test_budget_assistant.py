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


def test_overview_reflects_reimbursements_in_categories():
    # A linked reimbursement and a category-only reimbursement must reduce the
    # category (matching the dashboard) — not count as income or mere p2p netting.
    s = make_session()
    months = assistant._prev_complete_months(assistant.AVG_MONTHS)  # [newest, middle, oldest]
    newest, oldest = months[0], months[-1]
    ny, nm = int(newest[:4]), int(newest[5:7])
    oy, om = int(oldest[:4]), int(oldest[5:7])
    # anchor on the 1st of the oldest window month so all AVG_MONTHS months are covered
    s.add(Transaction(account_id=1, date=date(oy, om, 1), name="Anchor", amount=30.0, category="TRANSPORTATION"))
    dinner = Transaction(account_id=1, date=date(ny, nm, 12), name="Group dinner",
                         amount=180.0, category="FOOD_AND_DRINK")
    s.add(dinner); s.commit(); s.refresh(dinner)
    s.add(Transaction(account_id=1, date=date(ny, nm, 14), name="Zelle payment from Ryan",
                      amount=-60.0, category="TRANSFER_IN", reimburses_transaction_id=dinner.id))
    s.add(Transaction(account_id=1, date=date(ny, nm, 20), name="Zelle payment from Mom",
                      amount=-40.0, category="TRANSFER_IN", user_category="FOOD_AND_DRINK"))
    s.commit()

    data, _ = assistant._overview(s)
    n = data["months_averaged"]
    assert n == assistant.AVG_MONTHS
    food = next(c for c in data["avg_monthly_by_category"] if c["category"] == "FOOD_AND_DRINK")
    assert food["avg_monthly"] == round((180.0 - 60.0 - 40.0) / n, 2)  # 80 net, not 180
    assert data["avg_monthly_income"] == 0.0        # reimbursements are not income
    assert data["avg_monthly_p2p_net"] == 0.0       # they reduce the category, not the net


def test_add_category_persists():
    s = make_session()
    data, action = assistant._add_category(s, "gifts & donations")
    assert data == {"category": "GIFTS_&_DONATIONS", "created": True}
    assert "GIFTS_&_DONATIONS" in {c.name for c in s.exec(select(Category)).all()}
    # idempotent
    data2, _ = assistant._add_category(s, "GIFTS_&_DONATIONS")
    assert data2["created"] is False


def test_rule_tools_registered():
    names = {t["name"] for t in assistant.TOOLS}
    assert {"set_merchant_rule", "list_merchant_rules", "bootstrap_rules"} <= names
    assert {"set_merchant_rule", "list_merchant_rules", "bootstrap_rules"} <= set(assistant._HANDLERS)


def test_set_merchant_rule_tool_creates_rule():
    from app.budget.services import rules as rules_svc
    s = make_session()
    data, action = assistant._set_merchant_rule(s, "Safeway", "groceries")
    assert data["merchant"] == "safeway" and data["category"] == "GROCERIES"
    assert rules_svc.load_rules(s)["safeway"] == "GROCERIES"
    assert action is not None


def test_set_merchant_rule_tool_rejects_transfer_category():
    s = make_session()
    data, action = assistant._set_merchant_rule(s, "Safeway", "TRANSFER_OUT")
    assert "error" in data and action is None


def test_bootstrap_rules_tool_from_history():
    from app.budget.services import rules as rules_svc
    s = make_session()
    s.add(Transaction(account_id=1, date=date(2026, 7, 1), name="Chipotle", merchant_name="Chipotle",
                      amount=12.0, category="FOOD_AND_DRINK", user_category="EATING_OUT"))
    s.add(Transaction(account_id=1, date=date(2026, 7, 2), name="Chipotle", merchant_name="Chipotle",
                      amount=13.0, category="FOOD_AND_DRINK", user_category="EATING_OUT"))
    s.commit()
    data, action = assistant._bootstrap_rules(s)
    assert data["count"] == 1
    assert rules_svc.load_rules(s)["chipotle"] == "EATING_OUT"
    assert action is not None


def test_list_merchant_rules_tool():
    s = make_session()
    assistant._set_merchant_rule(s, "Safeway", "GROCERIES")
    data, _ = assistant._list_merchant_rules(s)
    assert data["count"] == 1 and data["rules"][0]["merchant"] == "safeway"


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


def test_run_assistant_never_returns_empty_reply_after_action():
    # The weak/cheap model sometimes ends a tool turn with no text. A blank reply must
    # never surface — fall back to summarizing what was done.
    s = make_session(); seed(s)
    tool_block = SimpleNamespace(type="tool_use", id="tu_1", name="set_budget",
                                 input={"category": "FOOD_AND_DRINK", "monthly_limit": 200})
    client = _FakeClient([
        _FakeResp("tool_use", [tool_block]),
        _FakeResp("end_turn", [SimpleNamespace(type="text", text="")]),
    ])
    result = assistant.run_assistant(s, [{"role": "user", "content": "set food budget 200"}], client=client)
    assert result["reply"].strip() != ""
    assert "FOOD_AND_DRINK" in result["reply"]
    assert result["refresh"] is True


def test_run_assistant_empty_reply_without_action_has_fallback():
    s = make_session()
    client = _FakeClient([_FakeResp("end_turn", [SimpleNamespace(type="text", text="   ")])])
    result = assistant.run_assistant(s, [{"role": "user", "content": "??"}], client=client)
    assert result["reply"].strip() != ""


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
