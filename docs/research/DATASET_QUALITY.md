# Dataset quality reports — Phase 2.1

Diagnostics that say whether a research dataset is **fit to use** before any
backtest exists. This is not a backtester, not a strategy layer, and not an
HTTP endpoint.

Package: `quant_platform.research.quality` (plus `quality_types`). It consumes
the Phase 2.0 dataset API. No new database tables.

## What a quality report is

A report (`DatasetQualityReport`) is a deterministic snapshot of:

- temporal coverage per instrument
- open sessions without a bar
- bars on closed sessions
- missing calendars
- point-in-time corrections visible at `as_of`
- stored corporate actions visible at `as_of` (not applied)
- ingestion runs / row errors tied to bars in the dataset
- quality issues with severity `info`, `warning`, or `error`

The same request against an unchanged database returns the same issue list,
coverage numbers, and JSON payload except `generated_at` (wall clock unless
injected).

## Why `as_of` is mandatory

Quality must not inspect information that was not knowable at the simulation
time. Bars, corrections, and corporate actions are included only when
`available_time <= as_of`. There is no implicit `latest=True`.

`build_dataset_quality_request` reuses `build_daily_bars_dataset_request`, so
naive timestamps, inverted ranges, and unbounded queries fail the same way.

## How severities are interpreted

| Severity | Meaning |
|----------|---------|
| `error` | The dataset contradicts the calendar or PIT contract in a way that should block research use of that slice (holiday bar, exceptional-close bar, lookahead if it ever leaked). |
| `warning` | Research can continue, but coverage is incomplete or audit raised a problem (`missing_calendar`, open session without a bar, long gap, ingestion rejections). |
| `info` | Context only: visible corporate actions, multiple sources on a day, PIT correction chains. |

An empty error list does **not** mean the history is complete. Check coverage
ratios and warnings.

## How coverage is calculated

For each instrument that matches the identity filter (including instruments
with **zero** bars):

- first / last observation among PIT-visible bars
- bar count and source names
- if a calendar is available: expected open sessions (`open` and
  `half_session` rows in `market_sessions` whose `session_date` falls in the
  civil window of `[start_time, end_time]`)
- coverage ratio = (open session dates with ≥1 bar) / (expected open sessions),
  quantized to 4 decimal places
- missing open sessions; bars on closed or unknown session dates

If there is no calendar, expected sessions are **not invented**. Coverage
ratio is `null` and a `missing_calendar` warning is emitted.

## How calendars are used

Quality does **not** filter the dataset the way `get_daily_bars_dataset` does
when `calendar_code` is set. Closed-session bars must remain visible so they
can be diagnosed.

Calendar resolution:

1. `calendar_code` on the quality request, if present (all instruments)
2. else `instruments.calendar_id`
3. else no calendar (`missing_calendar`)

Session rules:

- `open` and `half_session` require a bar (`open_session_without_bar` warning)
- `holiday` and `exceptional_close` must not require a bar; a bar there is an
  **error** (`bar_on_holiday`, `bar_on_exceptional_close`)
- a civil date with no `market_sessions` row is not assumed open
- `strict_calendar=True` promotes `bar_on_unknown_session` from warning to error

A consecutive streak of missing **open** sessions (in calendar order, not
raw weekdays) at least `long_gap_open_sessions` (default 5) emits `long_gap`.

## Corporate actions

`get_corporate_actions_for_dataset` supplies events with
`available_time <= as_of` and `effective_time` in the observation window.
They appear in `report.corporate_actions` and as `corporate_action_visible`
info issues. Splits are **not** applied. OHLCV is unchanged. Symbols are
not rewritten.

## Ingestion errors

Runs referenced by visible bars are summarized (`accepted_count`,
`rejected_count`). Row-level `ingestion_errors` for those runs become
`ingestion_error` warnings. `raw_payload` is not copied into the report.

Runs that rejected every row and therefore produced no bars are not attached
(there is no date join). That is intentional, not a vendor lookup.

## Script

```bash
uv run python scripts/report-dataset-quality.py \
  --symbol AAPL \
  --exchange XNAS \
  --start 2024-01-01T00:00:00Z \
  --end 2024-12-31T00:00:00Z \
  --as-of 2025-01-02T00:00:00Z \
  --calendar XNAS
```

`--as-of` is required. `--output PATH` writes JSON. The script does not print
`DATABASE_URL`. `--calendar` is used for diagnostics; it does not hide
holiday bars in the report.

Python:

```python
from quant_platform.research import (
    build_dataset_quality_request,
    get_dataset_quality_report,
)

request = build_dataset_quality_request(
    as_of=as_of,
    start_time=start,
    end_time=end,
    symbols=["FICT"],
    calendar_code="XNAS",
)
report = get_dataset_quality_report(session, request)
```

## Tests

```bash
uv run pytest -m "not postgres"    # request validation, coverage math, JSON
uv run pytest -m postgres          # calendars, PIT, corporate actions, ingest errors
```

## What does not exist

- backtesting, strategies, signals, indicators-as-signals
- portfolio, positions, trades, orders, execution, brokers
- paper trading, live trading, risk engine, optimizer, ML
- HTTP quality routes (still `GET /health` only)
- vendor downloads, LLM runtime
