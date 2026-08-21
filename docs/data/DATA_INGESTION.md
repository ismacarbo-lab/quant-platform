# Data ingestion — Phase 1.0

Research-only local OHLCV storage. No vendor APIs, brokers, strategies,
signals, or execution.

## Scope

This phase adds:

- `data_sources`, `instruments`, `ingestion_runs`, `daily_bars`
- point-in-time validation (`available_time > observation_time`)
- a local CSV loader
- `scripts/load-daily-bars.py`

It does **not** add market-data downloads, Yahoo/Polygon/Alpaca/IBKR, orders,
portfolios, or a backtester.

`APP_MODE` remains **research** only.

## Tables

| Table | Role |
|-------|------|
| `data_sources` | Named local source (`local_csv`, `manual_fixture`). `vendor` is a label, not a network client. |
| `instruments` | Research symbol (`symbol` unique in Phase 1.0). |
| `ingestion_runs` | One load attempt (`started` / `succeeded` / `failed`). |
| `daily_bars` | Daily OHLCV with `observation_time` and `available_time`. |

The JSON column on `ingestion_runs` is **`run_metadata`** (not `metadata`)
because SQLAlchemy reserves `metadata` on declarative classes.

Unique PIT key: `(instrument_id, source_id, observation_time, available_time)`.
Re-ingesting the same key is idempotent (insert is skipped).

## Point-in-time

- `observation_time` — when the bar refers to (CSV `date`; a calendar date is
  midnight UTC that day).
- `available_time` — earliest time the bar could have been known.
- Invariant (strict): **`available_time > observation_time`**. Equality is
  rejected so a same-timestamp “close” cannot leak into a simulation.

Reads: `get_daily_bars(..., as_of=simulation_time)` returns rows with
`available_time <= simulation_time`.

Timestamps are timezone-aware UTC.

## CSV format

```text
symbol,date,open,high,low,close,volume,available_time
FIXT,2024-01-02,10.00,11.00,9.50,10.50,1000,2024-01-03T00:00:00Z
```

- `date` → `observation_time`
- `available_time` is required and must include a timezone (`Z` or offset)
- `volume` may be empty
- `high >= low`, prices and volume non-negative
- `high` must be ≥ open and close; `low` must be ≤ open and close

Sample fixture: `tests/fixtures/daily_bars_sample.csv`.

## Commands

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run python scripts/check-db.py
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv \
  --source local_csv --vendor local_csv --asset-class equity
```

The loader prints `mode`, `source`, `symbols`, row counts. It does not print
`DATABASE_URL` or passwords.

Tests:

```bash
uv run pytest -m "not postgres"    # no Docker
uv run pytest -m postgres          # needs Postgres; applies migrations
```

## Not implemented

Strategies, signals, backtesting, risk, execution, orders, portfolio,
positions, trades, paper/live trading, brokers, scheduled jobs, extra HTTP APIs.
