from app.budget.models import Account, PlaidItem


def test_list_accounts(client, session):
    item = PlaidItem(plaid_item_id="i1", access_token="t")
    session.add(item); session.commit(); session.refresh(item)
    session.add(Account(plaid_account_id="a1", item_id=item.id, name="Checking",
                        type="depository", subtype="checking", current_balance=250.0))
    session.commit()

    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Checking"
    assert data[0]["current_balance"] == 250.0
