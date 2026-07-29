import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.budget.db import engine, init_db
from app.config import get_settings

app = FastAPI(title="Money API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5273"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request, call_next):
    """Protect tunneled development APIs with a pre-shared bearer token.

    Empty APP_API_KEY keeps localhost development frictionless. This is a
    temporary personal-testing gate, not a substitute for per-user auth.
    """
    configured = get_settings().app_api_key
    protected = request.url.path.startswith("/api/") and request.url.path != "/api/health"
    if configured and protected and request.method != "OPTIONS":
        authorization = request.headers.get("authorization", "")
        scheme, _, provided = authorization.partition(" ")
        valid = (
            scheme.lower() == "bearer"
            and bool(provided)
            and secrets.compare_digest(provided, configured)
        )
        if not valid:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Defense in depth: investing is read-only in this application. Keep unsafe
    # methods blocked even if a future route is accidentally registered. The
    # explicit order/trade prefixes also deny common mutation paths before they
    # exist, rather than relying on a 404/405 as the safety boundary.
    read_only_investing_paths = (
        "/api/portfolio",
        "/api/invest",
        "/api/orders",
        "/api/trades",
    )
    unsafe_method = request.method not in {"GET", "HEAD", "OPTIONS"}
    if unsafe_method and request.url.path.startswith(read_only_investing_paths):
        return JSONResponse(
            status_code=403,
            content={"detail": "Investing is read-only; trade mutations are disabled."},
        )
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Budgeting domain (Plaid transactions, categories, budgets, dashboard).
from app.budget.routers import accounts, budgets, dashboard, goals, plaid, rules, schedule, transactions

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(dashboard.router)
app.include_router(plaid.router)
app.include_router(rules.router)
app.include_router(goals.router)
app.include_router(schedule.router)

# Reviewed external API connectors and normalized goal measurements.
from app.auto_integration import router as auto_integration
from app.auto_integration.service import seed_builtin_connectors

app.include_router(auto_integration.router)

# Reusable image uploads for multimodal Copilot requests and future domains.
from app.media import router as media

app.include_router(media.router)

# Investing domain (read-only tastytrade portfolio).
from app.invest import portfolio

app.include_router(portfolio.router)

# Unified AI copilot: one /api/assistant/chat that delegates to the budgeting or
# investing specialist. Replaces the two apps' separate assistant endpoints.
from app.copilot import jobs as copilot_jobs
from app.copilot import router as copilot

app.include_router(copilot.router)
app.include_router(copilot_jobs.router)


@app.on_event("startup")
def _startup():
    init_db()
    with Session(engine) as session:
        seed_builtin_connectors(session)
