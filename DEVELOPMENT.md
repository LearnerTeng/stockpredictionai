# TradingAI Pro development guide

The current application is a front-end/back-end separated AI investment workbench.
The default portfolio and recommendations are explicitly marked as demo data, and
the trading workflow is paper-only.

## Architecture

```text
Vite + React + TypeScript :5173
           |
           v
Flask API gateway :8000
  |-- market data, prediction, recommendations, portfolio, paper orders
  |-- OpenAI/local prediction interpretation
  `-- image API proxy
           |
           v
FastAPI image service :8001
```

SQLite databases are stored under ignored `storage/` directories. Set
`STOCK_DATA_DB_PATH` and `TRADING_DB_PATH` to change their locations. PostgreSQL
is the intended next database once real accounts and larger imports are added.

## Install

```powershell
npm install
python -m pip install -r backend/requirements.txt
```

Copy `backend/.env.example` to `backend/.env` when OpenAI analysis is required.
Without an API key, `/ai/analyze` returns a deterministic local interpretation.

## Run

Start each process in a separate terminal:

```powershell
python backend/app.py
python -m uvicorn backend.image_service.main:app --host 127.0.0.1 --port 8001
npm run dev
```

Open `http://localhost:5173`. The main workbench uses hash routes, so static hosts
do not need special SPA fallback rules.

## Verify

```powershell
python -m unittest discover -s backend/tests -v
npm run typecheck
npm run build
npm audit --omit=dev
```

## Trading safety boundary

- Only `paper` mode exists in this version.
- Creating an order produces a draft and runs deterministic risk checks.
- A separate confirmation request is required before a simulated fill.
- The policy limits an order to `$10,000` and a position to 25% of equity.
- Broker credentials must never be stored in the browser.
- The recommendation score is deterministic; an LLM only explains model output.

Before real trading, add authentication, PostgreSQL migrations, broker sandbox
adapters, immutable audit events, market-hours checks, live price revalidation,
kill switches, and LangGraph human approval checkpoints.
