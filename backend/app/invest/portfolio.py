from fastapi import APIRouter, HTTPException

from app.invest import tasty

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio")
async def portfolio():
    try:
        session = tasty.get_session()
        return await tasty.fetch_portfolio(session)
    except RuntimeError as exc:  # credentials not configured
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — tastytrade/API failure
        raise HTTPException(status_code=502, detail=f"tastytrade error: {exc}")
