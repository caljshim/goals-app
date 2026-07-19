from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.budget.db import init_db

app = FastAPI(title="Money API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5273"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Budgeting domain (Plaid transactions, categories, budgets, dashboard).
from app.budget.routers import accounts, budgets, dashboard, goals, plaid, rules, transactions

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(dashboard.router)
app.include_router(plaid.router)
app.include_router(rules.router)
app.include_router(goals.router)

# Investing domain (read-only tastytrade portfolio).
from app.invest import portfolio

app.include_router(portfolio.router)

# Unified AI copilot: one /api/assistant/chat that delegates to the budgeting or
# investing specialist. Replaces the two apps' separate assistant endpoints.
from app.copilot import router as copilot

app.include_router(copilot.router)


@app.on_event("startup")
def _startup():
    init_db()
