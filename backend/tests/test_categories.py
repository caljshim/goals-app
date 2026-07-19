from datetime import date

from app.budget.categories import UNCATEGORIZED, effective_category, is_incoming_p2p
from app.budget.models import Transaction


def _txn(category=None, user_category=None):
    return Transaction(
        account_id=1, date=date(2026, 7, 1), name="x", amount=1.0,
        category=category, user_category=user_category,
    )


def _p2p_txn(category, name, user_category=None):
    return Transaction(
        account_id=1, date=date(2026, 7, 1), name=name, amount=-10.0,
        category=category, user_category=user_category,
    )


def test_is_incoming_p2p_true_for_zelle_transfer_in():
    assert is_incoming_p2p(_p2p_txn("TRANSFER_IN", "Zelle payment from Ryan")) is True


def test_is_incoming_p2p_false_for_outgoing():
    assert is_incoming_p2p(_p2p_txn("TRANSFER_OUT", "Venmo")) is False


def test_is_incoming_p2p_false_for_non_p2p_transfer():
    assert is_incoming_p2p(_p2p_txn("TRANSFER_IN", "Online Transfer from CHK ...4883")) is False


def test_is_incoming_p2p_uses_raw_category_not_effective():
    # A categorized incoming Zelle keeps its raw TRANSFER_IN category, so it's still detected.
    assert is_incoming_p2p(_p2p_txn("TRANSFER_IN", "Zelle from Mom", user_category="FOOD_AND_DRINK")) is True


def test_user_category_wins():
    assert effective_category(_txn(category="FOOD_AND_DRINK", user_category="DINING")) == "DINING"


def test_falls_back_to_plaid_category():
    assert effective_category(_txn(category="FOOD_AND_DRINK")) == "FOOD_AND_DRINK"


def test_uncategorized_when_both_missing():
    assert effective_category(_txn()) == UNCATEGORIZED
