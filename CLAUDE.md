# Working rules for this repo

`money/` is one project with two domains — **budgeting** (Plaid) and **investing**
(tastytrade) — plus a unified AI **copilot** that delegates to a specialist for each.

## Dev servers — do NOT kill them
- Never stop, kill, or restart the user's running backend (uvicorn, port **8100**) or
  frontend (Vite, port **5273**). The user runs them in their own terminals.
- Do not `taskkill` / kill processes on ports 8100 or 5273.
- Vite hot-reloads frontend edits automatically. If a backend restart is genuinely needed
  to pick up a change, tell the user and let them do it.

## No browser/Playwright verification
- Do NOT launch browser automation to visually verify frontend changes. Rely on
  `node_modules\typescript\bin\tsc -b`, lint, and the test suites.
- If something genuinely needs visual confirmation, describe what to look for.

## Money safety (this app can eventually place trades)
- `TASTYTRADE_ENV=prod` with the user's real account is allowed for READ-ONLY use
  (user decision 2026-07-16). The OAuth grant must have only the read/openid scopes —
  never create, request, or store a prod token with the trade scope in phase 1.
- Never write order-placing code paths without explicit, per-change user approval.
- External APIs (Plaid, tastytrade, Anthropic) are ALWAYS mocked in tests. Tests must
  never place orders, move money, or spend API credits.
- The copilot/agents must never execute a trade without an explicit user confirmation step.

## Structure
- Backend: FastAPI + SQLite in `backend/` (venv at `backend/.venv`), port 8100.
  - `app/budget/` — Plaid budgeting: models, db, categories, plaid_client, schemas,
    `routers/`, `services/` (incl. the budgeting specialist `services/assistant.py`).
  - `app/invest/` — tastytrade read-only: `tasty.py`, `portfolio.py` (router),
    `assistant.py` (investing specialist).
  - `app/copilot/` — orchestrator `agent.py` (tools `ask_budgeting`/`ask_investing`) +
    `router.py` serving the single `/api/assistant/chat`.
  - `app/config.py` — merged Settings (Plaid + tastytrade + Anthropic). One `.env`.
  - `app/main.py` — wires all routers.
- Frontend: React + Vite in `frontend/`, port 5273 (proxy targets 127.0.0.1:8100 —
  keep IPv4, `localhost` breaks on Windows). Tabs: Dashboard/Transactions/Accounts/
  Budgets/Invest, plus one `CopilotChat` sidebar.
- User data lives in `backend/money.db` (git-ignored).

## General
- Prefer minimal, focused edits over broad refactors. Keep the budgeting and investing
  domains separated in their subpackages; share only via `app/config.py` and the copilot.
- Don't guess the tastytrade SDK surface — introspect the installed package or check its
  docs before writing adapter code.
- Tests: `cd backend && .venv\Scripts\python.exe -m pytest -q`;
  `cd frontend && npm run test -- --run`.
