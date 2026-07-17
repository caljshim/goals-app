# Money

One personal-finance app with two domains and a unified AI copilot:

- **Budgeting** — bank transactions via Plaid, categories, budgets, and a dashboard.
- **Investing** — read-only tastytrade brokerage portfolio (balances, positions).
- **Copilot** — a single chat that delegates each question to a budgeting or investing
  specialist (and calls both for cross-domain questions like "how much spare cash could I
  invest?"). Education-forward and conservative; it cannot place trades.

Formed by merging the former `finance/` and `investor/` apps into one FastAPI backend
(separate routers per domain) and one React frontend.

## Architecture

```
backend/app/
  budget/    Plaid budgeting (models, db, categories, plaid_client, schemas, routers, services)
  invest/    tastytrade read-only (tasty.py, portfolio router, investing specialist)
  copilot/   orchestrator agent + /api/assistant/chat (delegates to the two specialists)
  config.py  merged settings   main.py  wires all routers
frontend/    React + Vite: Dashboard / Transactions / Accounts / Budgets / Invest + CopilotChat
```

## Setup

Backend (port 8100):
```
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # then fill in credentials
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8100
```

Frontend (port 5273):
```
cd frontend
npm install
npm run dev   # http://localhost:5273
```

## Credentials (`backend/.env`)
- **Plaid** — `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (https://dashboard.plaid.com).
- **tastytrade** — `TASTYTRADE_PROVIDER_SECRET` / `TASTYTRADE_REFRESH_TOKEN` (OAuth, from
  developer.tastytrade.com; both from the SAME OAuth app). `TASTYTRADE_ENV=prod` is the
  real account, READ-ONLY: create the personal grant with ONLY the read/openid scopes —
  no trade scope.
- **Anthropic** — `ANTHROPIC_API_KEY` (or `CLAUDE_API_KEY`); `ASSISTANT_MODEL` picks the
  copilot model.
- `DATABASE_URL` defaults to `sqlite:///./money.db`.

## Ports
Backend **8100**, frontend **5273**. The Vite proxy targets `127.0.0.1:8100` (IPv4 on
purpose — `localhost` resolves to `::1` first on Windows and breaks the proxy).

## Tests
- Backend: `cd backend && .venv\Scripts\python.exe -m pytest -q` (external APIs mocked).
- Frontend: `cd frontend && npm run test -- --run`.
