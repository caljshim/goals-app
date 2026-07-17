# Merge finance + investor into one project ("money") with a delegating copilot

**Date:** 2026-07-17
**Status:** Approved by user (repo home, frontend/chat shape, and copilot architecture each confirmed explicitly).

## Goal

Combine the `finance/` (Plaid budgeting tracker) and `investor/` (tastytrade portfolio
copilot) apps into one project with one backend, one frontend, and one AI copilot that
delegates to a budgeting agent or an investing agent. The two domains stay separate at
the code level via per-app FastAPI routers/subpackages.

## Decisions (user-approved)

1. **Repo home:** the `investor/` git repo is the home; the folder is renamed to
   `Documents/money/` (git history preserved — `.git` moves with the folder). Finance's
   code moves in. `finance/` is deleted from the Documents repo only after the user
   confirms the merged app works.
2. **Frontend:** one React app (finance's as the base) with the existing finance tabs
   plus a new **Invest** tab (ported Portfolio view). The two chat sidebars are replaced
   by ONE CopilotChat wired to the delegating agent.
3. **Copilot:** orchestrator + agents-as-tools. Top-level agent has exactly two tools —
   `ask_budgeting(question)` and `ask_investing(question)` — each runs the existing
   specialist (prompt + tools untouched) and returns its result; the orchestrator
   synthesizes, including cross-domain questions by calling both.

## Layout

```
money/
  CLAUDE.md, README.md          merged rules & docs
  backend/
    .env                        union: Plaid + tastytrade + Anthropic settings
    money.db                    finance's SQLite file, copied (user data)
    app/
      main.py                   one FastAPI app, port 8100
      config.py                 merged Settings (plaid + tastytrade + anthropic)
      budget/                   from finance/backend/app: models, db, categories,
                                plaid_client, schemas, routers/, services/
      invest/                   tasty.py, portfolio router, investing agent
      copilot/                  orchestrator agent + /api/assistant router
    tests/                      both suites (imports updated) + copilot tests
  frontend/                     finance frontend + Invest tab + CopilotChat, port 5273
```

## Backend

- One uvicorn on **8100**; CORS allows `http://localhost:5273`.
- URL paths unchanged: `/api/accounts`, `/api/transactions`, `/api/budgets`,
  `/api/dashboard`, `/api/plaid/*`, `/api/portfolio`, `/api/health`.
- The two old `/api/assistant` endpoints are replaced by a single `/api/assistant`
  running the copilot. Response shape matches finance's current one:
  `{reply, actions, refresh}` so the frontend refresh mechanism is unchanged.
- Package moves are mechanical: `app.models` → `app.budget.models`, etc. Each
  subpackage keeps its own routers; `main.py` only wires them.
- Merged `Settings`: finance's (database_url, plaid_*) + investor's (tastytrade_*,
  anthropic/assistant_model). One `.env`.
- Investor's money-safety rules carry into the merged CLAUDE.md verbatim: prod
  tastytrade is READ-ONLY (no trade scope), no order-placing code without explicit
  approval, external APIs always mocked in tests, agent never trades without user
  confirmation. Dev-server rules merge (never kill user terminals; ports 8100/5273).

## Copilot

- `app/copilot/agent.py`, same manual tool-use loop pattern as the specialists.
- Tools: `ask_budgeting(question: str)` — opens a DB session, calls the budgeting
  specialist's `run_assistant` with that question as a fresh single-message
  conversation, returns `{reply, actions}`; `ask_investing(question: str)` — calls the
  investing specialist, returns `{reply}`.
- Orchestrator system prompt: personal-money copilot; answers trivial/small-talk turns
  itself; delegates domain questions; for cross-domain questions calls both specialists
  and synthesizes; reports actions the budgeting agent took.
- Specialists are stateless per call: the orchestrator owns conversation history and
  formulates each delegated question.
- Specialist `actions` accumulate across tool calls and bubble into the API response
  (`refresh = bool(actions)`).
- Orchestrator `MAX_TOOL_ITERATIONS = 4`; all three agents use `settings.assistant_model`.

## Frontend

- Base: finance's app. New tab `Invest` renders the ported `Portfolio` component
  (types + `/api/portfolio` call moved into the merged `api.ts`/`types.ts`).
- `CopilotChat` replaces `AssistantChat` (finance) and `Chat` (investor): same UI and
  actions/refresh contract as `AssistantChat`, pointed at the unified `/api/assistant`,
  visible on all tabs.
- Vite proxy → `http://127.0.0.1:8100` (IPv4 — `localhost` breaks on Windows).
- The investor frontend is deleted.

## Error handling

- Copilot endpoint: 400 if `ANTHROPIC_API_KEY` missing, 502 on upstream/model failure
  (mirrors existing router patterns).
- A specialist exception inside a tool call becomes an error tool-result (JSON
  `{"error": ...}`) so the orchestrator explains instead of the request 500ing.
- Portfolio/tasty error mapping stays as-is (400 unconfigured / 502 API failure).

## Testing

- Move both pytest suites; update imports/paths. External APIs remain mocked — tests
  never hit Plaid, tastytrade, or Anthropic.
- New copilot tests with a fake Anthropic client: delegation dispatches to (mocked)
  specialists; actions bubble up and set `refresh`; specialist errors surface as error
  tool-results; unknown tool name handled.
- Frontend: `npx tsc -b` and `npm run test -- --run`.
- End-to-end verification after migration: full pytest, typecheck, then the user
  restarts their dev terminals (8100/5273) and confirms; only then is `finance/`
  removed from the Documents repo.

## Migration order

1. Rename `investor/` → `money/`; restructure backend into `budget`/`invest`/`copilot`
   subpackages (investor code first, then move finance code in).
2. Merge config, requirements, `.env`; copy finance's SQLite DB file.
3. Rebuild `backend/.venv` from merged requirements.
4. Implement copilot backend + tests.
5. Port frontend (Invest tab, CopilotChat, api/types/proxy merge).
6. Full verification; user restarts servers and confirms both domains + copilot work.
7. Retire `finance/` (delete from Documents working tree, local commit) and update
   memory notes.
