# Data ingestion — Phase 1.2

Research-only local OHLCV storage with bronze audit, instrument identity,
manual calendars, and explicit PIT corrections. No vendor APIs, brokers,
strategies, signals, or execution.

## Scope

Phase 1.2 adds:

- composite instrument identity (`symbol` is no longer globally unique)
- `instrument_identifiers` (local namespaces only)
- manual `market_calendars` / `market_sessions`
- optional calendar validation on CSV ingest (off by default)
- explicit silver corrections (`is_correction`, `supersedes_daily_bar_id`)

`APP_MODE` remains **research** only. There is no gold layer.

## Bronze vs silver

| Layer | Tables | Role |
|-------|--------|------|
| Bronze | `raw_ingestion_records`, `ingestion_errors` | Exact received payload, hash, and why a row was rejected. Append-only audit. |
| Silver | `daily_bars` | Validated, normalized OHLCV with point-in-time timestamps and optional correction links. |
| Gold | — | Not implemented. |

`data_sources`, `instruments`, `instrument_identifiers`, `market_calendars`,
`market_sessions`, and `ingestion_runs` are operational tables.

## Instrument identity

`instruments.id` remains the primary key. The natural key is:

```text
(symbol, asset_class, exchange, currency)
```

The same ticker may exist on two exchanges, in two currencies, or in two
asset classes. `symbol` alone is **not** unique.

PostgreSQL **`UNIQUE NULLS NOT DISTINCT`** (PG 15+) treats NULL `exchange` or
`currency` as equal, so two rows that omit exchange are the same instrument.

`upsert_instrument` matches that natural key and updates `name` / `calendar_id`
only. It does not rewrite the key fields.

## Alternate identifiers

`instrument_identifiers` stores local aliases. Namespaces are placeholders,
not vendor connections:

- `local_symbol`
- `figi_placeholder`
- `isin_placeholder`
- `vendor_symbol_placeholder`

Unique `(namespace, value, valid_from)` also uses `NULLS NOT DISTINCT`.
`valid_from` / `valid_to` are optional point-in-time bounds for the alias.

## Calendars (manual only)

`market_calendars` (`code`, `name`, IANA `timezone`) and `market_sessions`
(`session_date`, `is_open`, optional open/close times, `note`) are **fixtures**.
Nothing is downloaded from exchanges.

`instruments.calendar_id` is optional. With `validate_calendar=True` on ingest:

- instruments **without** a calendar skip the check
- instruments **with** a calendar need a session row for the observation
  civil date (in the calendar timezone) with `is_open=true`
- missing session or `is_open=false` → `ingestion_error` code `closed_session`,
  no silver row

Default is `validate_calendar=False` so simple fixtures keep working.

## Tables

| Table | Role |
|-------|------|
| `data_sources` | Named local source. `vendor` is a label, not a network client. |
| `instruments` | Research instrument; natural key `(symbol, asset_class, exchange, currency)`. |
| `instrument_identifiers` | Local aliases (no vendor APIs). |
| `market_calendars` | Manual calendar. |
| `market_sessions` | Open/closed civil dates. |
| `ingestion_runs` | One load attempt with `accepted_count` / `rejected_count`. |
| `raw_ingestion_records` | Bronze CSV row (`record_index` 0-based). |
| `ingestion_errors` | Rejected rows. |
| `daily_bars` | Silver OHLCV with PIT timestamps and optional correction link. |

Unique silver PIT key: `(instrument_id, source_id, observation_time, available_time)`.

## Point-in-time and corrections

Write invariant (strict): **`available_time > observation_time`**.

A correction is a **new** `daily_bars` row:

- `is_correction=true`
- `correction_reason` set
- `supersedes_daily_bar_id` points at the previous row
- `available_time` **after** the superseded bar’s `available_time`

History is never updated in place. `insert_daily_bar_correction` enforces this.

`get_daily_bars(..., as_of=simulation_time)` still:

1. Keeps `available_time <= simulation_time`
2. Returns the latest `available_time` per `(source_id, observation_time)`

Without `as_of`, every stored version is returned (audit).

## CSV format

```text
symbol,date,open,high,low,close,volume,available_time
FIXT,2024-01-02,10.00,11.00,9.50,10.50,1000,2024-01-03T00:00:00Z
```

One ingest file still maps all rows to the same `asset_class` / `exchange` /
`currency` / optional calendar (CLI flags). Distinct identities need separate
loads or repository calls.

### Error modes and calendar flag

| Mode | Default |
|------|---------|
| `collect_errors` | Script default |
| `fail_fast` | `--fail-fast` |
| `validate_calendar` | Off; `--validate-calendar` |

`--calendar CODE` attaches an **existing** `market_calendars.code`. Unknown
codes abort before a run is created.

Error codes include `lookahead`, `invalid_ohlc`, `closed_session`,
`stale_correction`, `invalid_timezone`, `naive_timestamp`, `empty_symbol`,
`empty_file`, `missing_columns`, `file_not_found`.

## Commands

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run python scripts/check-db.py
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv \
  --source local_csv --vendor local_csv --asset-class equity
```

Optional:

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_calendar.csv \
  --calendar TEST --validate-calendar
```

The loader does not print `DATABASE_URL`, passwords, or raw payloads.

Tests:

```bash
uv run pytest -m "not postgres"    # no Docker
uv run pytest -m postgres          # needs Postgres; applies migrations
```

## Not implemented

Gold layer, downloaded calendars, exchange connectivity, vendor APIs,
corporate actions, splits/dividends, strategies, signals, backtesting, risk,
execution, orders, portfolio, positions, trades, paper/live trading, brokers,
scheduled jobs, extra HTTP APIs.
