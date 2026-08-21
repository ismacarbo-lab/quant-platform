# quant_platform

Phase 0 foundation for a professional quantitative research platform.

This repository currently provides a **small, reproducible software base**:
typed configuration, UTC clocks, structured logging, a PostgreSQL-ready
storage layer, Alembic, and an internal health API. It is **not** a trading
system.

A pre-existing tree named `AI_VENTURE_OS_PROMPTS/` may sit next to this
project. It is a separate product and is **not** part of `quant_platform`.
Do not mix the two.

## Current purpose

- Run local research tooling on a safe default mode (`research`).
- Provide architectural boundaries for later data, risk, and execution work.
- Make behaviour testable without network access or vendor credentials.

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

```bash
uv run pytest
```

Unit tests do not call the network and do not require PostgreSQL to be running.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## PostgreSQL (local development)

```bash
docker compose up -d postgres
```

Default credentials in Compose and `.env.example` are **fictional local
placeholders**, not production secrets. Postgres is bound to `127.0.0.1:5432`.

Connection URL:

```text
postgresql+psycopg://quant:quant_dev_only_not_for_production@127.0.0.1:5432/quant_platform
```

## Migrations

Phase 0 has no financial schema and therefore **no Alembic revisions**.
Alembic is configured so future models registered on
`quant_platform.storage.database.Base` can generate migrations.

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

See `alembic/README.md`. Do not use SQLite as a stand-in for PostgreSQL.

## API

```bash
uv run uvicorn quant_platform.api.app:app --host 127.0.0.1 --port 8000
```

The only endpoint is:

```text
GET /health
```

It does not query the database or any external service.

## Architecture

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
and [docs/adr/0001-foundation-architecture.md](docs/adr/0001-foundation-architecture.md).
