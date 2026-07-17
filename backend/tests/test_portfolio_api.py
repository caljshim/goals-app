from datetime import datetime, timezone
from decimal import Decimal

from tastytrade.account import CurrentPosition
from tastytrade.order import InstrumentType

from app.invest import tasty
from app.invest import portfolio as portfolio_router

FAKE_PORTFOLIO = {
    "environment": "cert",
    "accounts": [{
        "account_number": "5WT00001", "nickname": "Sandbox", "type": "Margin",
        "net_liquidating_value": 10250.55, "cash_balance": 4200.10,
        "equity_buying_power": 8400.20, "derivative_buying_power": 4200.10,
        "maintenance_excess": 4200.10,
        "positions": [{
            "symbol": "VTI", "underlying_symbol": "VTI", "instrument_type": "Equity",
            "quantity": 20.0, "average_open_price": 280.5, "price": 302.5,
            "multiplier": 1, "market_value": 6050.0, "expires_at": None,
        }],
    }],
}


def test_position_normalizes_sdk_decimal_fields():
    # The real SDK model carries Decimal for every numeric field; _position must
    # normalize them all to float (real accounts crashed on float * Decimal).
    p = CurrentPosition(
        account_number="5WT00001", symbol="VTI", instrument_type=InstrumentType.EQUITY,
        underlying_symbol="VTI", quantity=Decimal("20"), quantity_direction="Long",
        close_price=Decimal("301.10"), average_open_price=Decimal("280.50"),
        multiplier=Decimal("1"), cost_effect="Credit", is_suppressed=False,
        is_frozen=False, realized_day_gain=Decimal("0"), realized_today=Decimal("0"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        mark_price=Decimal("302.50"),
    )
    pos = tasty._position(p)
    assert pos["market_value"] == 6050.0
    assert isinstance(pos["multiplier"], float)
    assert pos["quantity"] == 20.0
    assert pos["instrument_type"] == "Equity"


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_portfolio_returns_normalized_shape(client, monkeypatch):
    async def fake_fetch(s):
        return FAKE_PORTFOLIO
    monkeypatch.setattr(portfolio_router.tasty, "get_session", lambda: object())
    monkeypatch.setattr(portfolio_router.tasty, "fetch_portfolio", fake_fetch)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["environment"] == "cert"
    assert body["accounts"][0]["positions"][0]["symbol"] == "VTI"


def test_portfolio_unconfigured_is_400(client, monkeypatch):
    def boom():
        raise RuntimeError("tastytrade credentials are not configured")
    monkeypatch.setattr(portfolio_router.tasty, "get_session", boom)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


def test_portfolio_api_failure_is_502(client, monkeypatch):
    monkeypatch.setattr(portfolio_router.tasty, "get_session", lambda: object())
    async def boom(s):
        raise ValueError("token expired")
    monkeypatch.setattr(portfolio_router.tasty, "fetch_portfolio", boom)
    resp = client.get("/api/portfolio")
    assert resp.status_code == 502
    assert "token expired" in resp.json()["detail"]
