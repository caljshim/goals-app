"""Thin adapter over the tastytrade SDK (v13: OAuth sessions, pydantic models).

NOTE: the SDK is fully async (Account.get, get_balances, get_positions are all
`async def` despite sync-looking type hints) — everything here is async-first.

Read-only in phase 1: sessions, accounts, balances, positions. All numbers are
normalized to floats so responses JSON-serialize cleanly.
"""
from tastytrade import Account, Session

from app.config import get_settings


def get_session() -> Session:
    s = get_settings()
    if not (s.tastytrade_provider_secret and s.tastytrade_refresh_token):
        raise RuntimeError(
            "tastytrade credentials are not configured — set TASTYTRADE_PROVIDER_SECRET "
            "and TASTYTRADE_REFRESH_TOKEN in backend/.env (see .env.example)"
        )
    return Session(
        provider_secret=s.tastytrade_provider_secret,
        refresh_token=s.tastytrade_refresh_token,
        is_test=s.tastytrade_env.lower() != "prod",
    )


def _f(v) -> float | None:
    return None if v is None else float(v)


def _position(p) -> dict:
    qty = float(p.quantity)
    signed_qty = -qty if p.quantity_direction == "Short" else qty
    price = _f(p.mark_price) or _f(p.close_price) or 0.0
    multiplier = float(p.multiplier)
    return {
        "symbol": p.symbol,
        "underlying_symbol": p.underlying_symbol,
        "instrument_type": str(p.instrument_type),
        "quantity": signed_qty,
        "average_open_price": _f(p.average_open_price),
        "price": price,
        "multiplier": multiplier,
        "market_value": round(signed_qty * price * multiplier, 2),
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
    }


async def fetch_portfolio(session: Session) -> dict:
    accounts = await Account.get(session)
    out = []
    for acc in accounts:
        bal = await acc.get_balances(session)
        positions = await acc.get_positions(session, include_marks=True)
        out.append({
            "account_number": acc.account_number,
            "nickname": acc.nickname,
            "type": acc.margin_or_cash,
            "net_liquidating_value": _f(bal.net_liquidating_value),
            "cash_balance": _f(bal.cash_balance),
            "equity_buying_power": _f(bal.equity_buying_power),
            "derivative_buying_power": _f(bal.derivative_buying_power),
            "maintenance_excess": _f(bal.maintenance_excess),
            "positions": [_position(p) for p in positions],
        })
    return {"environment": get_settings().tastytrade_env, "accounts": out}
