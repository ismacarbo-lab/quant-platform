# Market calendars — Phase 1.4

Manual research calendars. Nothing is downloaded from an exchange.

## What exists

`market_calendars`: `code`, `name`, IANA `timezone`.

`market_sessions`: one civil date per calendar.

| `session_kind` | `is_open` | Meaning |
|----------------|-----------|---------|
| `open` | true | Regular session |
| `half_session` | true | Media sesión (still a trading day for daily bars) |
| `holiday` | false | Festivo |
| `exceptional_close` | false | Cierre excepcional |

`is_open` is kept in sync with `session_kind` (database check). Optional
`open_time` / `close_time` / `note` describe the session; they are not a
matching engine.

`instruments.calendar_id` is optional. CSV ingest
`validate_calendar=True` rejects a bar when the instrument has a calendar
and that civil date (in the calendar timezone) is missing or `is_open=false`.
Default remains **off**.

`create_calendar()` / `create_session()` persist fixtures.
`session_date_for_observation` converts a UTC observation to a civil date.

## What does not exist

- Official exchange calendars or holiday APIs
- Intraday session schedules, auctions, or halt calendars
- Automatic weekend inference (a missing date is “unknown”, not “closed”,
  unless you insert a session row)
- Timezone conversion of OHLCV prices

## Fixtures

- `tests/fixtures/market_calendars.csv`
- `tests/fixtures/market_sessions.csv`

Loaders: `load_calendars_csv`, `load_sessions_csv`.

## Later phases

Vendor calendars, per-exchange default calendars, and using sessions inside
a backtester belong later. This phase only stores what you type in.
