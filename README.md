# quant_platform

Phase 0 foundation for a professional quantitative research platform.

This repository currently provides a **research-only** software base:
typed configuration, UTC clocks, structured logging, PostgreSQL, Alembic,
an internal health API, **local CSV daily-bar ingestion** with point-in-time
timestamps, a **bronze audit layer**, an **instrument master** (exchanges,
composite identity, identifiers), **manual calendars**, **stored
corporate actions** (not applied to prices), a **research dataset API**
(`as_of` required), **dataset quality reports**, **local dataset
snapshots**, a **PostgreSQL snapshot catalog**, **deterministic
dataset replay** with an auditable event stream, **replay-run
artifacts** with a PostgreSQL metadata catalog, a **backtest
readiness gate**, a **dry-run backtest engine**
(`NoOpBacktestPolicy` / `ResearchPolicy`: counts, hashes, observations,
no orders), **backtest artifact integrity**, a **research-policy
interface** without signals, **policy-output observation reports**, and
a **backtest experiment registry** that groups dry-runs, an **experiment
usability gate**, **aggregated experiment research reports**,
**data-quality research policies**, and a **ResearchPolicy regression
matrix** (still no PnL or orders). Phase 5.2 adds a **research-mode
release candidate** check and status report.
It is **not** a trading system.

A pre-existing tree named `AI_VENTURE_OS_PROMPTS/` may sit next to this
project. It is a separate product and is **not** part of `quant_platform`.
Do not mix the two.

## Current purpose

- Load local daily OHLCV CSV into PostgreSQL with point-in-time fields.
- Keep bronze raw records and row-level ingestion errors for audit.
- Identify instruments by `(symbol, asset_class, exchange_id, currency)`.
- Build deterministic research datasets with a mandatory `as_of`.
- Diagnose dataset coverage, calendar gaps, PIT corrections, and ingestion errors
  before any backtest exists.
- Save a local, hashed snapshot of a dataset request, CSV, and quality report.
- Register snapshot metadata in PostgreSQL (hashes, request, relative artifacts).
- Verify local snapshot artifacts and catalog hashes without rewriting files.
- Replay a PIT dataset or local snapshot as an ordered market-event timeline.
- Audit that stream (session/CA events, stream hash, replay boundaries)
  before any backtest exists.
- Export a replay run as local JSON/JSONL artifacts and register metadata
  (hashes, counts, boundary status) in PostgreSQL.
- Compare registered replay runs and gate whether a run is ready for a
  dry-run backtest (no strategy, PnL, or orders).
- Consume a ready replay run with `NoOpBacktestPolicy`, write local
  summary/manifest artifacts, and register metadata in PostgreSQL.
- Verify local backtest artifacts, recompute hashes, compare two
  dry-runs, and gate whether a NoOp result is usable research evidence.
- Observe a replay stream through a registered `ResearchPolicy`
  (`noop` / `event_counting` / `data_quality` / `coverage` /
  `corporate_action_audit` / `correction_audit`) that emits
  observations and counters only.
- Group several dry-run backtests under a hashed experiment record
  (same replay with allowed configs, or several replays with one policy).
- Gate whether a registered experiment is usable research evidence and
  write an aggregated observation report (counts and hashes only).
- Observe replay quality through registered policies (`data_quality`,
  `coverage`, `corporate_action_audit`, `correction_audit`) without
  signals or orders.
- Pin ResearchPolicy outputs with a golden regression matrix (hashes and
  observation counts; still no PnL).
- Run a research-mode release candidate check (status, guardrails, policy
  regression; still no trading or AI runtime).

## What is not implemented

- Strategies and BUY/SELL signals
- Machine learning or LLM runtime
- Real backtester (PnL, portfolio, orders); only a NoOp dry-run exists
- Market-data download or vendor APIs
- Broker connectivity
- Paper trading
- Live trading or order routing
- Frontend
- Kafka, Redis, Celery, Kubernetes, microservices

Live trading is not a configurable mode. `APP_MODE=live` (and `paper`) is
rejected by settings validation.

## AI usage boundary

Cursor (and similar editors) may be used to **write** this codebase. They
are **not** part of the running platform: not a dependency, not required
for tests or CI, and not a trading brain.

A future research assistant, if added, must be optional, off by default,
auditable, and unable to write market data or place orders. There is **no**
OpenAI, Anthropic, Cursor API, or local-model integration in this phase.

Policy: [docs/ai/AI_USAGE_BOUNDARY.md](docs/ai/AI_USAGE_BOUNDARY.md) and
[docs/adr/0002-ai-usage-boundary.md](docs/adr/0002-ai-usage-boundary.md).

## Prerequisites

- Python 3.13 (installed automatically by `uv` if missing)
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose (only if you need a local PostgreSQL)
- Git

## Installation

```bash
uv python install 3.13
uv sync
```

Copy the example environment file if you need local overrides:

```bash
cp .env.example .env
```

`.env` is gitignored. Use only fictional local values.

## Tests

Fast tests (no Docker, no PostgreSQL):

```bash
uv run pytest -m "not postgres"
```

All tests (Postgres-marked tests skip if the database is down):

```bash
uv run pytest
```

Postgres-only:

```bash
uv run pytest -m postgres
```

Full command list: [docs/development/DEVELOPER_WORKFLOW.md](docs/development/DEVELOPER_WORKFLOW.md).

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not postgres"
docker compose config
```

Or `make quality`. GitHub Actions (`.github/workflows/ci.yml`) runs the same
fast path on every push/PR, plus a Postgres job. No GitHub secrets.
First push and how to read Actions:
[docs/development/DEVELOPER_WORKFLOW.md](docs/development/DEVELOPER_WORKFLOW.md#remote-first-push-and-github-actions).

## PostgreSQL (local development)

Host **5432** is already used on this machine by another container
(`ia_postgres`). **5433** is used by `postgres_db`. This project therefore
maps PostgreSQL to **`127.0.0.1:5434`** (container port remains 5432).

```bash
cp .env.example .env   # if .env does not exist; gitignored
docker compose up -d postgres
docker compose ps
docker compose logs postgres --tail=50
```

Wait until the `postgres` service is healthy. Then:

```bash
uv run python scripts/check-db.py
```

That command loads settings, opens a SQLAlchemy connection, runs `SELECT 1`,
lists public tables, and exits non-zero if any domain table exists. It does
not create tables.

Stop:

```bash
docker compose down
```

`docker compose down` keeps the named volume. Use `docker compose down -v`
only if you intend to wipe the local database.

Default credentials in Compose and `.env.example` are **fictional local
placeholders**, not production secrets. Postgres is bound to `127.0.0.1:5434`.

Connection URL:

```text
postgresql+psycopg://quant:quant_dev_only_not_for_production@127.0.0.1:5434/quant_platform
```

There are still **no** trading tables (orders, fills, signals, strategies).
Alembic revisions `0001_ingestion` … `0009_backtest_experiments` create
research ingestion, instrument-master, snapshot-catalog, replay-run,
dry-run backtest, and backtest-experiment metadata tables only.

## Migrations

Apply research schema (PostgreSQL only):

```bash
uv run alembic current
uv run alembic upgrade head
```

Do not use SQLite. See `alembic/README.md`.

APP_MODE remains **research** only.

## API

```bash
uv run uvicorn quant_platform.api.app:app --host 127.0.0.1 --port 8000
```

The only endpoint is:

```text
GET /health
```

It does not query the database or any external service.

Data ingestion (local CSV only):
[docs/data/DATA_INGESTION.md](docs/data/DATA_INGESTION.md),
[docs/data/INSTRUMENT_MASTER.md](docs/data/INSTRUMENT_MASTER.md),
[docs/data/MARKET_CALENDARS.md](docs/data/MARKET_CALENDARS.md),
[docs/data/CORPORATE_ACTIONS.md](docs/data/CORPORATE_ACTIONS.md).

Research datasets (Python API + optional CSV export):
[docs/research/RESEARCH_DATASETS.md](docs/research/RESEARCH_DATASETS.md).
Dataset quality reports (coverage, calendars, PIT, ingestion errors):
[docs/research/DATASET_QUALITY.md](docs/research/DATASET_QUALITY.md).
Reproducible local snapshots (CSV + quality JSON + hashed manifest):
[docs/research/DATASET_SNAPSHOTS.md](docs/research/DATASET_SNAPSHOTS.md).
Snapshot catalog (PostgreSQL metadata, hashes, list/compare):
[docs/research/DATASET_CATALOG.md](docs/research/DATASET_CATALOG.md).
Snapshot integrity (local artifact and catalog verification):
[docs/research/SNAPSHOT_INTEGRITY.md](docs/research/SNAPSHOT_INTEGRITY.md).
Dataset replay (ordered market events, not a backtester):
[docs/simulation/DATASET_REPLAY.md](docs/simulation/DATASET_REPLAY.md).
Replay boundaries (`ReplayStartedEvent` first, pre-known facts):
[docs/simulation/REPLAY_BOUNDARIES.md](docs/simulation/REPLAY_BOUNDARIES.md).
Replay audit (stream hash, order, PIT checks):
[docs/simulation/REPLAY_AUDIT.md](docs/simulation/REPLAY_AUDIT.md).
Replay runs (local artifacts + PostgreSQL metadata catalog):
[docs/simulation/REPLAY_RUNS.md](docs/simulation/REPLAY_RUNS.md).
Backtest readiness (compare runs; gate, not a strategy):
[docs/simulation/BACKTEST_READINESS.md](docs/simulation/BACKTEST_READINESS.md).
Dry-run backtest engine (NoOp policy, no orders or PnL):
[docs/backtest/BACKTEST_ENGINE.md](docs/backtest/BACKTEST_ENGINE.md).
Backtest artifact integrity (verify, compare, usable_result):
[docs/backtest/BACKTEST_INTEGRITY.md](docs/backtest/BACKTEST_INTEGRITY.md).
Research policy interface (observations, not strategies):
[docs/backtest/RESEARCH_POLICY_INTERFACE.md](docs/backtest/RESEARCH_POLICY_INTERFACE.md).
Policy output reports and integrity:
[docs/backtest/POLICY_OUTPUT_INTEGRITY.md](docs/backtest/POLICY_OUTPUT_INTEGRITY.md).
Backtest experiments (group dry-runs; not a strategy):
[docs/backtest/BACKTEST_EXPERIMENTS.md](docs/backtest/BACKTEST_EXPERIMENTS.md).
Experiment usability and aggregated research reports:
[docs/backtest/BACKTEST_EXPERIMENT_USABILITY.md](docs/backtest/BACKTEST_EXPERIMENT_USABILITY.md).
Data-quality research policies (not strategies):
[docs/backtest/DATA_QUALITY_POLICIES.md](docs/backtest/DATA_QUALITY_POLICIES.md).
Research-policy regression matrix (golden hashes, not PnL):
[docs/backtest/POLICY_REGRESSION_MATRIX.md](docs/backtest/POLICY_REGRESSION_MATRIX.md).
Research-mode release candidate (what is ready, what is not):
[docs/release/RESEARCH_RELEASE_CANDIDATE.md](docs/release/RESEARCH_RELEASE_CANDIDATE.md).

See [docs/development/DEVELOPER_WORKFLOW.md](docs/development/DEVELOPER_WORKFLOW.md)
for install, Compose, Alembic, port 5434 conflicts, and CI.

## Architecture

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md),
[docs/adr/0001-foundation-architecture.md](docs/adr/0001-foundation-architecture.md),
and [docs/adr/0002-ai-usage-boundary.md](docs/adr/0002-ai-usage-boundary.md).
