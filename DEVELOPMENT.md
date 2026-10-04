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

Legacy SQLite databases are stored under ignored `storage/` directories. The
research, market-data and paper-trading repositories use PostgreSQL when `DATABASE_URL` is set;
without it, the app retains the SQLite compatibility path. SQLAlchemy models and
Alembic own the unified PostgreSQL schema.

## Install

```powershell
npm install
python -m pip install -r backend/requirements.txt
python -m pip install -r backend/requirements-ml.txt   # optional: gradient-boosted forecaster
```

Copy `backend/.env.example` to `backend/.env` when OpenAI analysis is required.
Without an API key, `/ai/analyze` returns a deterministic local interpretation.
Without `requirements-ml.txt`, the app falls back to the statistical forecaster.

## PostgreSQL setup

```powershell
docker compose up -d postgres
python -m alembic upgrade head
python backend/scripts/migrate_sqlite_to_database.py `
  --database-url postgresql+psycopg://stockapp:stockapp_local@127.0.0.1:5432/stockpredictionai
```

Set the same URL as `DATABASE_URL` in `backend/.env`. The migration is
idempotent and imports instruments, daily bars, portfolio state, positions,
recommendations, paper orders, preferences and settings. Legacy bars whose
instrument row is missing are recovered with an explicit migration note.

Alembic is the only schema creation path for PostgreSQL. Do not call
`Base.metadata.create_all()` from application startup.

## Run

Start each process in a separate terminal:

```powershell
python backend/app.py
python backend/scripts/ingestion_worker.py
python backend/scripts/news_worker.py
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

## Quant core

- `contracts.py`: fixed US-equity objective contract. Online structured output
  reports direct 5/20 trading-day excess return versus SPY, adjusted-price
  semantics, dataset version, model id, data cutoff and fallback state.
- Online Flask requests do not fit optional ML models. Set MODEL_REGISTRY_DIR to load an eligible registered model; otherwise
  excess-return output uses the explicit
  `relative-momentum-baseline-v1` fallback. Set `ENABLE_WEB_MODEL_TRAINING=true`
  only for local research access to `/model/compare`.

- `backtesting.py`: event-driven threshold backtester. Signals are computed on
  day `t` close and filled on day `t+1` (default open) with configurable
  commission and slippage, so results contain no intraday look-ahead. Reports
  Sharpe, max drawdown, win rate and total costs alongside the equity curve.
- `ml_models.py` / `ml_features.py`: optional gradient-boosted forecaster that
  trains on bar-derived features (trend, RSI, MACD, ATR, volatility, volume
  flow) to predict next-bar returns and compounds them recursively. Implements
  the same contract as `StatisticalForecaster` and degrades gracefully.
- `validation.py`: expanding-window walk-forward evaluation shared by
  `/predict` and `/model/compare`, so reported MAE/RMSE are multi-fold
  out-of-sample estimates instead of a single end-of-series holdout.
- `portfolio_risk.py`: portfolio-level risk analytics for `/portfolio/risk` —
  correlation matrix, annualized volatility, Sharpe, max drawdown, HHI
  concentration and volatility-inverse suggested weights.

## Data ingestion

- `POST /data/ingestion/jobs` queues a 10-year Yahoo import and automatically
  includes SPY as the benchmark. The request returns HTTP 202 immediately.
- `GET /data/ingestion/jobs/{id}` reports queued, running, completed, partial or
  failed state, retry count and per-symbol errors.
- Jobs are idempotent on symbol and trade date, retry transient symbol failures,
  persist raw/adjusted OHLCV plus dividend/split events, and reject overlapping
  local jobs.
- The Flask process runs one local worker for convenience. The standalone
  `ingestion_worker.py` recovers queued jobs after a restart and is the preferred
  process boundary for longer imports.

## News sentiment

- Run `python backend/scripts/news_worker.py` as a separate server-side process.
  It recovers queued jobs and schedules incremental US/JP news refreshes every
  30 minutes even when the browser is closed. Use `--once` for one cycle or
  `--backfill --once` for a quota-aware best-effort historical import.
- GDELT supplies multilingual incremental coverage. Set
  `ALPHA_VANTAGE_API_KEY` to add ticker-level news and historical sentiment;
  the free request budget defaults to 20 calls per UTC day and is persisted in
  PostgreSQL.
- Japanese news and articles without provider sentiment use the configured
  OpenAI model. Without an OpenAI key, articles remain visible with a pending
  analysis state and are retried by later worker cycles.
- Email alerts require `SMTP_HOST`, `SMTP_FROM`, and optional authentication
  variables from `backend/.env.example`. Recipients and the enable switch are
  configured from the Market Sentiment page; SMTP passwords never enter the UI
  or database.
- The `/predict` response includes research-only `sentiment_context` and
  `sentiment_shadow` fields. These do not modify recommendation scores or paper
  orders.

## Trading safety boundary

- Only `paper` mode exists in this version.
- Creating an order produces a draft and runs deterministic risk checks.
- A separate confirmation request is required before a simulated fill.
- The policy limits an order to `$10,000` and a position to 25% of equity.
- Broker credentials must never be stored in the browser.
- The recommendation score is deterministic; an LLM only explains model output.

Before real trading, validate broker sandbox adapters, immutable external audit
storage, exchange calendars, live price freshness, partial fills and reconciliation.
The local API access gate and paper halt control below are not broker risk controls.


## Quant integrity and paper execution hardening (2026-09-06)

Monitoring and backtesting now use the same `forecast_signal` function with all
bars known at the signal cutoff. `history_window` is honored. Backtests normalize
adjusted OHLC, reject duplicate/nonfinite price rows, include initial cash in the
risk curve and emit one equity point per date. A changed historical OHLCV or
benchmark value changes the full SHA-256 dataset version. Portfolio risk uses
adjusted closes and the selected account's performance history. The initial Alembic
revision now contains frozen table definitions instead of importing the current ORM;
fresh SQLite/PostgreSQL upgrades can apply the subsequent account and news revisions
without duplicate columns. Existing databases already at head are unaffected.

Paper orders use one `paper-v2` policy across legacy SQLite and SQLAlchemy:

- Account mutations serialize with PostgreSQL row locks or SQLite BEGIN IMMEDIATE.
- Pending buys reserve cash and position capacity; pending sells reserve quantity.
- Confirmation re-reads the latest stored price and checks the full policy again.
- Market orders cannot smuggle a limit price; nonfinite quantities/prices are rejected.
- A limit order fills only when the stored reference satisfies its limit. It remains
  a snapshot-based simulator: no exchange queue, volume or partial-fill model yet.
- Draft confirmation expires after 15 minutes. Cancel an expired draft to release
  its reservations. Reservations are conservative until explicitly cancelled.
- Repeated confirmation/cancellation is idempotent. Reusing an Idempotency-Key
  with a different order is rejected. State history is recorded in risk-result JSON;
  this is operational history, not immutable external audit storage.
- `/trading/control` GET/PUT accepts `{ "halted": true/false }`. Halt blocks new
  drafts and confirmations while cancellation remains available. The state is
  persisted and the Trading page exposes pause/resume and cancel controls.

Ingestion workers claim queued jobs with an atomic conditional update so two
processes cannot execute the same job. Running jobs interrupted by a process crash
are not automatically reclaimed: inspect the job/process before explicitly resetting
its state, since blind retries could overlap a worker that is still alive.

## Offline model research and registry

Install `backend/requirements-ml.txt`. Run from the repository root:

```powershell
python backend/scripts/quant_research.py train --symbol AAPL
python backend/scripts/quant_research.py list
python backend/scripts/quant_research.py activate <run_id>
python backend/scripts/quant_research.py score --symbol AAPL
```

Use `--registry <directory>` BEFORE the subcommand to select another registry.
`train` and `score` read stored AAPL and SPY bars, without network calls. For exact
replays, pass `train --symbol AAPL --dataset <run-directory>/dataset.json`. Input
JSON contains `symbol`, `stock` and `benchmark` daily-bar arrays.

Every successful candidate saves its full dataset snapshot, content digest,
5/20-day expanding validation observations, runtime/feature versions, source-code
snapshots and hashes, model parameters, trained model
and 0x/1x/2x cost sensitivity of the existing threshold strategy. That strategy
report evaluates the heuristic trading rule; it is not a backtest of the new model.
Evaluation origins are 20 bars apart and training labels end at or before each
origin. At least three folds are needed to report results; serving activation
requires at least twelve folds for EACH horizon and MAE strictly better than both
relative-momentum and zero-excess baselines. This is a research-serving gate, not a
profitability or live-trading gate. Do not repeatedly tune on these folds and then
call them an untouched holdout.

Set `MODEL_REGISTRY_DIR=backend/storage/research` for `/predict` to load the active
per-symbol artifact. Active selections are replaced atomically. Activate an earlier
eligible run to roll back; previous selections are recorded under `activations/`.
Only one operator should change active selections at a time. The server never
fits these models. A missing, corrupt, incompatible or >90-day-old artifact produces
an explicit fallback with `registry_error`. The registry must be operator-owned:
its pickle artifacts are executable Python objects; hashes detect corruption,
not malicious replacements. Never accept a registry directory or artifact from an
untrusted API upload.

With a registry configured, predictions are archived under `predictions/`. The
`score` command evaluates matured horizons after refreshing local market data,
counts duplicate cutoff/model/horizon requests once and excludes requests recorded
on or after their first outcome-bar date. Results are saved under `evaluations/`.
The cutoff is intentionally conservative at the daily level. Data older than seven
calendar days is marked stale; no registered model is labelled production eligible.
The registered excess model stays separate from the existing heuristic scoring and
paper order flow until portfolio-level validation supports replacing that strategy.

The top-level `/predict` `predictions`/`actuals` still describe the historical price
holdout for compatibility. Forward excess returns live in `quant_forecast`. Do not
interpret historical holdout prices as future executable targets. `future_forecast`
contains the forward price forecast and its reference cutoff; the Stock page uses
this field and displays the excess-return model/fallback status explicitly.

## API deployment and operational checks

Development binds to 127.0.0.1 with Flask debug disabled. The API rejects remote
requests unless `API_ACCESS_TOKEN` is configured; with a token configured, every
non-OPTIONS request must send `Authorization: Bearer <token>`. Allowed browser
origins are set by `CORS_ORIGINS` and checked before mutations. Restrict origins to
those you operate. For remote browser access, use an authenticated TLS reverse
proxy that injects the server-side token. Do not put it in a VITE_* variable or
browser storage. Multi-user identities/roles are still a separate deployment task.

The GitHub Actions workflow runs backend checks, isolated PostgreSQL transaction
tests, TypeScript checking and the frontend production build. Locally:

```powershell
$env:OMP_NUM_THREADS = '1'
python -m unittest discover -s backend/tests -v
npm run typecheck
npm run build
```

Set `TEST_POSTGRES_URL` to enable PostgreSQL integration tests. Each test creates
and removes its own random `quant_test_*` schema, never the application schema.
Back up the application PostgreSQL database using pg_dump and separately copy the
trusted research registry. Restore into a separate database first, run Alembic and
verify counts, cash/holdings and artifact hashes before changing the application URL.
An automated restore drill, broker reconciliation, historical universe coverage,
portfolio optimization and sustained forward trading remain explicit next milestones.
