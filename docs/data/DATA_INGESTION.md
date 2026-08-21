# Data ingestion — Phase 1.1

Research-only local OHLCV storage with a bronze audit layer. No vendor APIs,
brokers, strategies, signals, or execution.

## Scope

Phase 1.0 stored silver `daily_bars`. Phase 1.1 adds:

- bronze `raw_ingestion_records` (payload + SHA-256)
- bronze `ingestion_errors` (row-level quality failures)
- `ingestion_runs.accepted_count` / `rejected_count`
- CSV ingest that can **collect-errors** (default) or **fail-fast**
- as-of reads that pick the latest visible PIT correction

`APP_MODE` remains **research** only. There is no gold layer.

## Bronze vs silver

| Layer | Tables | Role |
|-------|--------|------|
| Bronze | `raw_ingestion_records`, `ingestion_errors` | Exact received payload, hash, and why a row was rejected. Append-only audit. |
| Silver | `daily_bars` | Validated, normalized OHLCV with point-in-time timestamps. |
| Gold | — | Not implemented (features, signals, backtest artifacts). |

`data_sources`, `instruments`, and `ingestion_runs` are shared operational
tables, not a medallion layer.

## Tables

| Table | Role |
|-------|------|
| `data_sources` | Named local source (`local_csv`, `manual_fixture`). `vendor` is a label, not a network client. |
| `instruments` | Research symbol (`symbol` unique in this phase). |
| `ingestion_runs` | One load attempt. Counters: `row_count`, `accepted_count`, `rejected_count`. |
| `raw_ingestion_records` | One bronze row per CSV data row (`record_index` is 0-based). |
| `ingestion_errors` | Rejected rows (or empty-file). |
| `daily_bars` | Silver daily OHLCV with `observation_time` and `available_time`. |

The JSON column on `ingestion_runs` is **`run_metadata`**.

`payload_hash` is SHA-256 of canonical JSON (sorted keys, compact separators)
after secret-like keys are replaced with `[redacted]`. There is an **index**
on `(source_id, payload_hash)` so duplicates can be found. It is **not**
unique: the same payload may appear in more than one run, and bronze keeps
both for audit.

Unique bronze key: `(ingestion_run_id, record_index)`.

Unique silver PIT key: `(instrument_id, source_id, observation_time, available_time)`.
A later correction is a **new** silver row with a new `available_time`, never
an in-place overwrite.

### Counters

`accepted_count` and `rejected_count` are stored on `ingestion_runs` (not
derived at read time) so a finished run is inspectable without joins.
`row_count` is the number of CSV data rows processed (`accepted + rejected`
in the Phase 1.1 pipeline).

## Point-in-time and as-of

- `observation_time` — when the bar refers to (CSV `date`; a calendar date is
  midnight UTC that day).
- `available_time` — earliest time the bar could have been known.
- Write invariant (strict): **`available_time > observation_time`**.

`get_daily_bars(..., as_of=simulation_time)`:

1. Keeps rows with `available_time <= simulation_time` (no future versions).
2. For each `(source_id, observation_time)`, returns the row with the latest
   `available_time` (latest correction known at that simulation time).

Without `as_of`, every stored PIT version is returned (audit).

Example: same observation day, `available_time` 2024-01-02 and 2024-01-05.
As-of 2024-01-03 → first. As-of 2024-01-06 → second.

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

Fixtures: `tests/fixtures/daily_bars_sample.csv`,
`tests/fixtures/daily_bars_mixed.csv`.

### Error modes

| Mode | Library | Script |
|------|---------|--------|
| `collect_errors` | Continue after a bad row | **Default** |
| `fail_fast` | Stop after the first bad row | `--fail-fast` |

File/header problems (missing file, missing columns) always abort before
rows are stored. Bronze is written **before** silver validation.

Error codes include `lookahead`, `invalid_ohlc`, `naive_timestamp`,
`invalid_number`, `empty_symbol`, `empty_file`, `missing_columns`,
`file_not_found`.

## Commands

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run python scripts/check-db.py
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv \
  --source local_csv --vendor local_csv --asset-class equity
```

Collect-errors is the default. Fail-fast:

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_mixed.csv --fail-fast
```

The loader prints `mode`, `source`, `error_mode`, `accepted_count`,
`rejected_count`, `inserted_rows`, and `error_codes` when present. It does
not print `DATABASE_URL`, passwords, or raw payloads.

### How to read errors

Use `list_ingestion_errors(session, ingestion_run_id=...)` and
`get_raw_records_for_run(session, ingestion_run_id=...)`, or SQL:

```sql
SELECT record_index, error_code, error_message
FROM ingestion_errors
ORDER BY record_index NULLS LAST, created_at;
```

Tests:

```bash
uv run pytest -m "not postgres"    # no Docker
uv run pytest -m postgres          # needs Postgres; applies migrations
```

## Not implemented

Gold layer, corporate actions, calendars, survivorship bias, strategies,
signals, backtesting, risk, execution, orders, portfolio, positions, trades,
paper/live trading, brokers, scheduled jobs, extra HTTP APIs.
