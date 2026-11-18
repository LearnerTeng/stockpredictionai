# NVIDIA advice runtime

This addition is for personal testing and evaluation. Public data freshness and
inference capacity are independent: checking every minute does not provide live
quotes. NVIDIA account limits and structured-output support require live account
validation. No NVIDIA key was present during implementation.

## Start

Install dependencies with `npm ci` and `python -m pip install -r backend/requirements.txt`.
Start Docker Desktop and the existing database with `docker compose up -d postgres`.
Back up an existing database before running `python -m alembic upgrade head`.
Then run `npm run start:all`. The launcher checks migration and ports, starts API,
Vite, image service, news/research workers and separate advice scheduler/executor,
and stops only its own children on Ctrl+C. It does not start a Windows service.

Set NVIDIA_API_KEY only in ignored backend/.env. Explicit LLM_* provider/model
overrides take precedence over NVIDIA defaults. Never use VITE_* for secrets.
Enable automatic analysis in the AI assistant settings after checking the account
and symbols. Default is disabled to allow inspection before background usage.

## Interfaces and persistence

- GET /advice?symbol=NVDA&portfolio_id=primary: latest 30 tasks including older reports.
- POST /advice/jobs: symbol, portfolio_id, language; optional kind=review/question,
  parent_id of a completed report and question. Returns 202 and a durable task ID.
- GET /advice/jobs/{id}: task state, safe error class and result.
- GET/PUT /ai/settings: enabled, interval_seconds, rpm, target_rpm,
  background_rpm, concurrency, position_limit, allocation_targets, keyword_only.
  Long-term allocation keys are portfolio_id:symbol, with fractional targets.
- GET /ai/status: model configuration presence, recent usage, task totals, last success.
- POST /ai/vision: multipart file and language; public PNG/JPEG/WebP charts up to
  8 MB and 20 million pixels. Input is re-encoded and resized before cloud inference.

Migration 0008 adds advice_jobs (immutable input snapshot and completed report)
and ai_calls (quota reservation and outcome). Settings use existing app_settings.
The queue claims a four-minute lease in a short transaction before network I/O.
Expired leases recover; completion must match the lease token. Five non-quota
failures exhaust a task. Submitting that task manually retries it. Missing keys
and shared capacity waits do not consume failure attempts. Identical requests
reuse reports; changed queued analyses supersede previous queued versions.

NVIDIA reservations are serialized through a PostgreSQL transaction advisory
lock. Defaults: hard setting 40 RPM, admission 36 RPM, background 28 RPM, two
concurrent calls, rolling 60 seconds. All local NVIDIA clients share this budget,
including news experiments. 429 cooldown is account-wide and honors Retry-After.
Separate apps using the same key are outside this local ledger. Reserve lower
limits if the account supplies less capacity.

## Decisions and limitations

Rules v1 use local monitoring scores: >50 permits conditional consideration of a
buy, <35 for a held security flags conditional reduction, otherwise hold/watch.
An exceeded configured position limit flags concentration. Missing recent news
or a quote older than the latest completed market session blocks a fresh buy
recommendation. These thresholds are research heuristics, not calibrated advice.
NISA uses allocation targets and snapshot information, not short-term timing.
US 5/20-session forecasts use the existing deterministic baseline; JP uses
indicators and evidence. The model explains rules and cannot update accounts.

Model prompts receive public evidence and derived risk conditions, not account
identifiers, cash or quantities. Quotes must exist verbatim in the referenced
frozen document. This checks reference integrity, not semantic entailment.
The explanatory summary still needs human review. News experiments remain
independent from follow-up Ultra reviews. Existing paper-order confirmation is
required and retains its own checks. Vision results are chart observations and
do not modify price data or trading signals.

Automatic market fetch is incremental (one-month overlap) every 15 minutes;
advice checks default to 60 seconds. News retains its own configured interval
and provider daily budget. Fund snapshots are manually maintained. Keyword
research is the free default; vector research requires keyword_only=false and
an explicitly configured embedding account. No paid fallback is automatic.

## Skills and source references

Reviewed NVIDIA/skills nvidia-skill-finder and rag-eval (version 2.6.0) on
2026-11-04. The finder catalog informs endpoint/workflow selection. rag-eval
requires the NVIDIA RAG Blueprint corpus/train.json evaluator and is not used
as an executable workflow here. Existing project citation and retrieval tests
remain the evaluation mechanism; no extra skills or GPU stack were installed.

- https://docs.nvidia.com/skills/
- https://github.com/NVIDIA/skills/blob/main/skills/rag-eval/SKILL.md
- https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash
- https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b
- https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b
- https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b

Run python backend/scripts/run_checks.py, npm run typecheck, npm run build.
Set TEST_POSTGRES_URL to a dedicated test database for PostgreSQL tests; never
point it at the business database. Real endpoint quality and speed remain
unverified until NVIDIA_API_KEY is configured and public-data smoke tests pass.

## Verification in this workspace

- Backend suite: 128 tests, 116 passed, 12 PostgreSQL tests skipped.
- Two additional shared-quota PostgreSQL tests were collected and skipped because
  TEST_POSTGRES_URL is unavailable.
- TypeScript checking, Vite production build, and Python compilation passed.
- Docker Desktop was launched, but its WSL engine failed to become available;
  logs report WslUpdateRequired. Business database migration and PostgreSQL
  concurrency verification were not performed.
- `python backend/scripts/check_nvidia.py` reported missing-key for all four
  configured task roles. Run it after providing the key and database.
