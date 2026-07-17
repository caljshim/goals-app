from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.budget.models import Account, Budget, PlaidItem, Transaction


def make_engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


def test_crud_all_models():
    eng = make_engine()
    with Session(eng) as s:
        item = PlaidItem(plaid_item_id="item_1", access_token="tok")
        s.add(item)
        s.commit()
        s.refresh(item)

        acct = Account(plaid_account_id="acc_1", item_id=item.id, name="Checking", type="depository")
        s.add(acct)
        s.commit()
        s.refresh(acct)

        txn = Transaction(account_id=acct.id, date=date(2026, 7, 1), name="Coffee", amount=4.50)
        s.add(txn)
        s.add(Budget(category="FOOD_AND_DRINK", monthly_limit=300.0))
        s.commit()

        assert s.exec(select(Transaction)).one().name == "Coffee"
        assert s.exec(select(Budget)).one().monthly_limit == 300.0
