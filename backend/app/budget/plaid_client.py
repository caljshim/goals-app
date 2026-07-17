import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_refresh_request import TransactionsRefreshRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from app.config import get_settings

_ENV_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def get_client() -> plaid_api.PlaidApi:
    s = get_settings()
    config = plaid.Configuration(
        host=_ENV_HOSTS.get(s.plaid_env, plaid.Environment.Sandbox),
        api_key={"clientId": s.plaid_client_id, "secret": s.plaid_secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(config))


def create_link_token(client) -> str:
    s = get_settings()
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="local-user"),
        client_name="Finance Tracker",
        products=[Products(p) for p in s.plaid_products.split(",")],
        country_codes=[CountryCode(c) for c in s.plaid_country_codes.split(",")],
        language="en",
    )
    return client.link_token_create(req).link_token


def exchange_public_token(client, public_token: str) -> dict:
    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    return {"access_token": resp.access_token, "item_id": resp.item_id}


def _balance(acc):
    b = acc.balances
    return b.current, b.available, (b.iso_currency_code or "USD")


def fetch_accounts(client, access_token: str) -> list[dict]:
    resp = client.accounts_get(AccountsGetRequest(access_token=access_token))
    out = []
    for a in resp.accounts:
        current, available, currency = _balance(a)
        out.append({
            "plaid_account_id": a.account_id,
            "name": a.name,
            "official_name": a.official_name,
            "type": str(a.type),
            "subtype": str(a.subtype) if a.subtype else None,
            "mask": a.mask,
            "current_balance": current,
            "available_balance": available,
            "currency": currency,
        })
    return out


def _norm_txn(t) -> dict:
    pfc = getattr(t, "personal_finance_category", None)
    return {
        "plaid_transaction_id": t.transaction_id,
        "plaid_account_id": t.account_id,
        "date": t.date,
        "name": t.name,
        "merchant_name": getattr(t, "merchant_name", None),
        "amount": t.amount,
        "category": pfc.primary if pfc else None,
        "pending": t.pending,
    }


def refresh_transactions(client, access_token: str) -> None:
    """Ask Plaid to re-pull this item from the bank right now (async on Plaid's side;
    new data arrives via a subsequent transactions_sync). May incur a per-call fee."""
    client.transactions_refresh(TransactionsRefreshRequest(access_token=access_token))


def sync_transactions(client, access_token: str, cursor: str | None) -> dict:
    kwargs = {"access_token": access_token}
    if cursor:
        kwargs["cursor"] = cursor
    resp = client.transactions_sync(TransactionsSyncRequest(**kwargs))
    return {
        "added": [_norm_txn(t) for t in resp.added],
        "modified": [_norm_txn(t) for t in resp.modified],
        "removed": [r.transaction_id for r in resp.removed],
        "next_cursor": resp.next_cursor,
        "has_more": resp.has_more,
    }
