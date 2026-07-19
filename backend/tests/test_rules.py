from datetime import date

from app.budget.categories import effective_category, merchant_key
from app.budget.models import Transaction


def _txn(**kw):
    d = dict(account_id=1, date=date(2026, 7, 1), name="x", amount=1.0)
    d.update(kw)
    return Transaction(**d)


def test_merchant_key_normalizes_merchant_name_then_name():
    assert merchant_key(_txn(merchant_name="Safeway", name="SAFEWAY #1234 CA")) == "safeway"
    assert merchant_key(_txn(merchant_name=None, name="  Blue Bottle  ")) == "blue bottle"
    assert merchant_key(_txn(merchant_name=None, name="")) == ""


def test_effective_category_precedence():
    rules = {"safeway": "GROCERIES"}
    # one-off user_category wins over a rule
    assert effective_category(
        _txn(merchant_name="Safeway", category="FOOD_AND_DRINK", user_category="EATING_OUT"), rules
    ) == "EATING_OUT"
    # rule applies when there is no one-off
    assert effective_category(_txn(merchant_name="Safeway", category="FOOD_AND_DRINK"), rules) == "GROCERIES"
    # no rule -> raw Plaid category
    assert effective_category(_txn(merchant_name="Chipotle", category="FOOD_AND_DRINK"), rules) == "FOOD_AND_DRINK"


def test_rules_are_skipped_for_transfers():
    # Even if a rule keys the merchant, a transfer's raw category means it's ignored,
    # so the Zelle/card-payment logic stays intact.
    rules = {"zelle payment to ryan uyeki jpm9": "ENTERTAINMENT"}
    t = _txn(merchant_name=None, name="ZELLE PAYMENT TO RYAN UYEKI JPM9", category="TRANSFER_OUT")
    assert effective_category(t, rules) == "TRANSFER_OUT"


def test_effective_category_without_rules_is_unchanged():
    assert effective_category(_txn(category="FOOD_AND_DRINK")) == "FOOD_AND_DRINK"
    assert effective_category(_txn(category="FOOD_AND_DRINK", user_category="DINING")) == "DINING"
    assert effective_category(_txn()) == "UNCATEGORIZED"
