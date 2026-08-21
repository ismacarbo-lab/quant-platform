# Data ingestion — Phase 1.4

Research-only local OHLCV storage with bronze audit, instrument master,
manual calendars, corporate-action **storage**, and explicit PIT
corrections. No vendor APIs, brokers, strategies, signals, or execution.

## Scope

Phase 1.4 adds:

- `exchanges` and `instruments.exchange_id` (no global unique `symbol`)
- identifier namespaces `isin` / `figi` / `cusip` / `local_symbol` /
  `vendor_symbol` (strings only; no lookups)
- session kinds: open, holiday, half session, exceptional close
- `corporate_actions` storage (not applied to prices)
- bidirectional correction pointers (`supersedes` / `superseded_by`)

`APP_MODE` remains **research** only. There is no gold layer.

Details:

- [Instrument master](INSTRUMENT_MASTER.md)
- [Market calendars](MARKET_CALENDARS.md)
- [Corporate actions](CORPORATE_ACTIONS.md)

## Bronze vs silver

| Layer | Tables | Role |
|-------|--------|------|
| Bronze | `raw_ingestion_records`, `ingestion_errors` | Exact received payload, hash, and why a row was rejected. Append-only audit. |
| Silver | `daily_bars` | Validated, normalized OHLCV with point-in-time timestamps and correction links. |
| Gold | — | Not implemented. |

`data_sources`, `exchanges`, `instruments`, `instrument_identifiers`,
`market_calendars`, `market_sessions`, `corporate_actions`, and
`ingestion_runs` are operational tables.

## Instrument identity

Natural key:

```text
(symbol, asset_class, exchange_id, currency)
```

PostgreSQL **`UNIQUE NULLS NOT DISTINCT`** (PG 15+) treats NULL `exchange_id`
or `currency` as equal. `symbol` alone is **not** unique. Currency stays in
the key so the same venue can list the same ticker in two quote currencies.

`upsert_instrument` matches that key. `--exchange CODE` must resolve to
`exchanges.code` (`unknown_exchange` otherwise). The load script creates a
local stub venue when `--exchange` is passed.

## Point-in-time and corrections

Daily bars (strict): **`available_time > observation_time`**.

A correction is a **new** `daily_bars` row:

- `is_correction=true`
- `correction_reason` set
- `supersedes_daily_bar_id` points at the previous row
- `superseded_by_daily_bar_id` on the previous row is a **pointer only**
  (OHLC on that row is never rewritten)
- correction `available_time` **after** the superseded bar’s `available_time`

`get_daily_bars(..., as_of=simulation_time)`:

1. Keeps `available_time <= simulation_time`
2. Returns the latest `available_time` per `(source_id, observation_time)`

Without `as_of`, every stored version is returned (audit).

Corporate actions use `effective_time` (economic) and `available_time`
(knowable). Announcement may precede effect; that is not a daily-bar
lookahead violation. `list_corporate_actions(..., as_of=)` filters by
`available_time`. **No price adjustment is applied.**

## Tables

| Table | Role |
|-------|------|
| `data_sources` | Named local source. `vendor` is a label, not a network client. |
| `exchanges` | Research venue (`code`, optional MIC, timezone, country, currency). |
| `instruments` | Natural key `(symbol, asset_class, exchange_id, currency)`. |
| `instrument_identifiers` | Local aliases (no vendor APIs). |
| `market_calendars` | Manual calendar. |
| `market_sessions` | Civil dates: open / holiday / half_session / exceptional_close. |
| `corporate_actions` | Stored events; not applied. |
| `ingestion_runs` | One load attempt with `accepted_count` / `rejected_count`. |
| `raw_ingestion_records` | Bronze CSV row (`record_index` 0-based). |
| `ingestion_errors` | Rejected rows. |
| `daily_bars` | Silver OHLCV with PIT timestamps and correction links. |

Unique silver PIT key: `(instrument_id, source_id, observation_time, available_time)`.

## CSV format

```text
symbol,date,open,high,low,close,volume,available_time
FIXT,2024-01-02,10.00,11.00,9.50,10.50,1000,2024-01-03T00:00:00Z
```

One ingest file still maps all rows to the same `asset_class` / `exchange` /
`currency` / optional calendar (CLI flags). Distinct identities need separate
loads or repository calls.

Reference fixtures (fictional, not market data dumps):
`tests/fixtures/exchanges.csv`, `market_sessions.csv`,
`corporate_actions.csv`.

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
`empty_file`, `missing_columns`, `file_not_found`, `unknown_exchange`,
`invalid_namespace`, `invalid_action_type`, `invalid_session_kind`.

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
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv \
  --exchange XNYS --exchange-timezone America/New_York
```

The loader does not print `DATABASE_URL`, passwords, or raw payloads.

Tests:

```bash
uv run pytest -m "not postgres"    # no Docker
uv run pytest -m postgres          # needs Postgres; applies migrations
```

## Not implemented

Gold layer, downloaded calendars, exchange/MIC/FIGI/ISIN APIs, applying
corporate actions to prices, strategies, signals, backtesting, risk,
execution, orders, portfolio, positions, trades, paper/live trading, brokers,
scheduled jobs, extra HTTP APIs.
