# quant_platform

Phase 0 foundation for a professional quantitative research platform.

This repository currently provides a **research-only** software base:
typed configuration, UTC clocks, structured logging, PostgreSQL, Alembic,
an internal health API, **local CSV daily-bar ingestion** with point-in-time
timestamps, and a **bronze audit layer** (raw payloads, hashes, row errors).
It is **not** a trading system.

A pre-existing tree named `AI_VENTURE_OS_PROMPTS/` may sit next to this
project. It is a separate product and is **not** part of `quant_platform`.
Do not mix the two.

## Current purpose

- Load local daily OHLCV CSV into PostgreSQL with point-in-time fields.
- Keep bronze raw records and row-level ingestion errors for audit.
- Run local research tooling on a safe default mode (`research`).

## What is not implemented

- Strategies and BUY/SELL signals
- Machine learning
- Backtester
- Market-data download or vendor APIs
- Broker connectivity
- Paper trading
- Live trading or order routing
- Frontend
- Kafka, Redis, Celery, Kubernetes, microservices

Live trading is not a configurable mode. `APP_MODE=live` (and `paper`) is
rejected by settings validation.

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

There are still **no domain tables** (candles, quotes, trades, orders, fills,
signals, strategies). Alembic may create only `alembic_version` as bookkeeping.

## Migrations

Phase 0 has no financial schema and therefore **no domain Alembic revisions**.
Alembic is configured so future models registered on
`quant_platform.storage.database.Base` can generate migrations.

```bash
uv run alembic current
uv run alembic upgrade head
```

With no revisions, `upgrade head` is a no-op for domain schema. Do not use
SQLite. See `alembic/README.md`.

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
[docs/data/DATA_INGESTION.md](docs/data/DATA_INGESTION.md).

See [docs/development/DEVELOPER_WORKFLOW.md](docs/development/DEVELOPER_WORKFLOW.md)
for install, Compose, Alembic, port 5434 conflicts, and CI.

## Architecture

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
and [docs/adr/0001-foundation-architecture.md](docs/adr/0001-foundation-architecture.md).
