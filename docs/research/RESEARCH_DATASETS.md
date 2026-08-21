# Research datasets — Phase 2.0

Internal Python API to build **deterministic, point-in-time** daily OHLCV
tables from silver storage. This is not a backtester, not a strategy layer,
and not an HTTP endpoint.

Package: `quant_platform.research` (query/export). Ingestion stays in
`quant_platform.data`. No new database tables.

## What a research dataset is

A dataset is the result of a typed query (`DailyBarsDatasetRequest`) against
PostgreSQL:

- identity filters (symbol, instrument id, exchange, asset class, currency)
- observation window `[start_time, end_time]`
- mandatory `as_of`
- optional manual calendar filter
- stable column order
- stable sort: symbol, exchange code, instrument id, observation time, source

The same request against an unchanged database returns the same rows.

## Why `as_of` is mandatory

Without `as_of`, a query could silently include corrections that would not
have been knowable at a simulation time. There is **no** implicit
`latest=True`. `build_daily_bars_dataset_request` rejects a missing or naive
`as_of`.

`quant_platform.data.repository.get_daily_bars` still allows omitting `as_of`
for **audit** (every PIT version). Dataset builders must not use that path.

Rule: keep `available_time <= as_of`. If several silver rows share
`(instrument_id, source_id, observation_time)`, keep the one with the latest
`available_time` still `<= as_of`.

## Calendars

Pass `calendar_code` (and/or `require_open_session=True`, which **requires**
`calendar_code`). Calendars are not inferred from `instruments.calendar_id`.

- `open` and `half_session` are kept (`is_open=true`)
- `holiday` and `exceptional_close` are dropped
- a bar whose civil date has **no** `market_sessions` row is an error
  (`incomplete_calendar`) — the API does not invent weekends or holidays
- unknown `calendar_code` is an error

If you do not pass a calendar, session tables are ignored.

## Corporate actions

`get_corporate_actions_for_dataset(session, request)` returns stored events
with `available_time <= as_of` and `effective_time` inside the observation
window. Splits are **not** applied. OHLCV is unchanged. Symbols are not
rewritten.

## Unbounded queries

A request needs at least one identity filter (`symbols`, `instrument_ids`,
`exchange_codes`, `asset_classes`, or `currency`) **or** explicit
`allow_unfiltered=True`. Time range alone is not enough.

## Export

CSV only (`csv` stdlib). **No Parquet** — that would add pyarrow/pandas.

```bash
uv run python scripts/export-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output /tmp/daily-dataset.csv
```

Optional `--corporate-actions-output PATH` writes the matching stored events.
`--allow-unfiltered` is required if you omit identity flags. The script does
not print `DATABASE_URL`.

Python:

```python
from quant_platform.research import (
    build_daily_bars_dataset_request,
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
    write_daily_bars_csv,
)

request = build_daily_bars_dataset_request(
    as_of=as_of,
    start_time=start,
    end_time=end,
    symbols=["FIXT"],
)
dataset = get_daily_bars_dataset(session, request)
write_daily_bars_csv(dataset, Path("daily-dataset.csv"))
```

Quality reports (`get_dataset_quality_report`) consume this API. They do
**not** filter out holiday bars: closed-session rows must stay visible so
coverage diagnostics can flag them. See
[DATASET_QUALITY.md](DATASET_QUALITY.md).

Local hashed snapshots (CSV + quality JSON + manifest) are documented in
[DATASET_SNAPSHOTS.md](DATASET_SNAPSHOTS.md).

## Tests

```bash
uv run pytest -m "not postgres"    # request validation, CSV, no Docker
uv run pytest -m postgres          # PIT, calendars, corporate actions
```

## What does not exist

- HTTP dataset routes (still `GET /health` only)
- pandas / Parquet
- adjusted prices, signals, indicators-as-signals
- backtesting, strategies, portfolio, risk, execution, brokers
- vendor downloads, ML, LLM runtime
- dataset quality is documented in [DATASET_QUALITY.md](DATASET_QUALITY.md);
  it is a report, not a backtester
- local snapshots are documented in [DATASET_SNAPSHOTS.md](DATASET_SNAPSHOTS.md);
  they are folders on disk, not a catalog or object store
