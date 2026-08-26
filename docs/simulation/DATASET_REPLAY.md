# Dataset replay — Phase 3.0

Replay turns a **point-in-time daily-bar dataset** into a deterministic
sequence of market events. It is the foundation for a future backtester.
It is **not** backtesting, not a strategy, and not trading.

Package: `quant_platform.simulation`.

## What replay is

Given a dataset (from PostgreSQL or a local snapshot):

1. emit `ReplayStartedEvent`
2. emit one `MarketBarEvent` per visible bar, in stable order
3. emit `ReplayFinishedEvent`
4. return an immutable `DailyBarReplay` plus a `ReplaySummary`

Same dataset + same request + same code version produces the same event
order and the same summary fields (except a random `replay_id` unless the
caller supplies one).

`started_at` / `finished_at` on the summary are **simulation timeline**
bounds (request `start_time` and last bar `available_time`, or `end_time`
if there are no bars). They are not wall-clock times.

There is **no** Alembic table for replay runs.

## Why this is not backtesting yet

Replay only walks market data. It does not:

- generate signals or run a strategy
- keep a portfolio or positions
- create orders, fills, or trades
- model slippage, commissions, or brokers
- persist a simulation run

A future backtester should consume these events. It does not exist yet.

## Why `event_time = available_time`

A daily bar has two times:

| Field | Meaning |
|-------|---------|
| `observation_time` | The session/day the OHLCV describes |
| `available_time` | The earliest time that bar could have been known |

Replay sets `MarketBarEvent.event_time` to **`available_time`**, never to
`observation_time`. The simulation clock therefore cannot “see” a close
on the session date if the bar only became knowable later (including PIT
corrections).

If those two timestamps differ, the event still carries both fields.

This is a different use of the name `event_time` than the architecture
table that pairs `event_time` with economic occurrence. On a replay
event, `event_time` is the **simulation instant** at which the bar may
be consumed.

## How lookahead is avoided

- Dataset query: `available_time <= as_of` (Research Dataset API).
- Replay: reject any bar with `available_time > as_of`.
- Clock: `SimulationClock.advance_to` is monotonic UTC; it cannot move
  backwards.
- Bar sort: primary key is `available_time`, then symbol, exchange,
  instrument id, observation time, source. Dataset table order
  (observation time) is **not** the replay order.

Invariant while the clock sits at `simulation_time`:

```text
available_time <= simulation_time
```

Naive (timezone-less) timestamps are rejected.

## Calendars and sessions

Replay does not re-implement calendars. If the dataset request includes
`calendar_code` / `require_open_session`, `get_daily_bars_dataset` already
drops holiday (and optionally closed) sessions. Snapshot CSV is whatever
that query wrote. Replay emits only those rows.

## Events

| Kind | Role |
|------|------|
| `replay_started` | Window `start_time` / `end_time` / `as_of`, instrument count |
| `market_bar` | One PIT-visible daily bar |
| `replay_finished` | Counts and timeline bounds |

There are no order, signal, or portfolio events.

## Sources

### Database

```python
from quant_platform.simulation import create_daily_bar_replay
from quant_platform.research.types import build_daily_bars_dataset_request

replay = create_daily_bar_replay(session, request)
```

`create_daily_bar_replay` calls `get_daily_bars_dataset`.
`replay_daily_bars_dataset` accepts an in-memory `DailyBarsDataset`.

### Snapshot

```python
from quant_platform.simulation import replay_daily_bars_snapshot

replay = replay_daily_bars_snapshot("/path/to/snapshot")
```

This reads `manifest.json` and `daily_bars.csv`, runs the existing
artifact verification (`verify_snapshot_artifacts`), and does **not**
query PostgreSQL. A broken folder (hash mismatch, missing file) fails
with `broken_snapshot`.

## Script

Database replay (`--as-of`, `--start`, `--end` required):

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT
```

Snapshot replay (no database):

```bash
uv run python scripts/replay-daily-dataset.py \
  --snapshot-dir /tmp/fixt-snapshot \
  --json
```

Prints `replay_id`, counts, and first/last event times. `--json` prints
the summary mapping. It does not print `DATABASE_URL`. It does not trade.

## What does not exist

- strategies, signals, indicators-as-signals
- backtesting engine, optimizer, risk engine
- orders, trades, fills, portfolio, positions
- brokers, paper trading, live trading
- HTTP routes beyond `GET /health`
- persisted simulation runs
- ML / LLM runtime, vendor downloads
