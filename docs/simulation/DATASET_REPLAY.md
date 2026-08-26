# Dataset replay — Phase 3.1

Replay turns a **point-in-time daily-bar dataset** into a deterministic
sequence of simulation events. Phase 3.1 adds optional session and
corporate-action events, a stream hash, and an audit report. It is
**not** backtesting, not a strategy, and not trading.

Package: `quant_platform.simulation`.

Audit details: [REPLAY_AUDIT.md](REPLAY_AUDIT.md).

## What replay is

Given a dataset (from PostgreSQL or a local snapshot):

1. emit `ReplayStartedEvent`
2. emit optional `MarketSessionEvent` rows (local calendar)
3. emit optional `CorporateActionEvent` rows (stored facts, not applied)
4. emit one `MarketBarEvent` per visible bar
5. emit `ReplayFinishedEvent`
6. return an immutable `DailyBarReplay` plus a `ReplaySummary`

The full list is sorted by the canonical key below. `ReplayStartedEvent`
and `ReplayFinishedEvent` participate in that sort (they are not forced
to the ends if a payload event has an earlier `available_time`).

Same dataset + same request + same extras + same code version produces
the same event order and the same `stream_hash`. `replay_id` is UUID4
unless `deterministic_id=True`.

`started_at` / `finished_at` on the summary are **simulation timeline**
bounds, not wall-clock times.

There is **no** Alembic table for replay runs.

## Event priority

When `event_time` ties, kinds sort as:

1. `replay_started`
2. `market_session`
3. `corporate_action`
4. `market_bar`
5. `replay_finished`

Then: instrument (or calendar code), observation / effective /
`session_date`, source / `action_type` / `session_kind`, stable id.

## Why `event_time = available_time`

Bars and corporate actions use **`available_time`**, never
`observation_time` / `effective_time`, as `event_time`. The clock cannot
see a close or a split before it was knowable. Both timestamps stay on
the event.

Session events are **not** PIT market data. Calendars in this platform
are local static fixtures with no separate published-at timestamp.
`event_time` is `session_date` at `open_time` in the calendar timezone,
or midnight local if `open_time` is null, converted to UTC. A session
with `event_time > as_of` is omitted.

## Corporate actions

`include_corporate_actions=False` by default (Phase 3.0 bar-only stream).

When `True`, `create_daily_bar_replay` loads
`get_corporate_actions_for_dataset` (`available_time <= as_of`, effective
time in `[start, end]`). Replay **does not** apply splits, adjust OHLCV,
or rename symbols. `value` is a display string (cash amount, new value,
or `quantity_before:quantity_after`).

## Sessions

`include_sessions=False` by default.

When `True` **and** the request has `calendar_code`, replay emits every
stored session in the observation window: `open`, `half_session`,
`holiday`, and `exceptional_close`. Missing dates are not invented.
Without `calendar_code` the flag is a no-op (audit records an info).

Snapshot folders do not store sessions or corporate actions. Those flags
on `--snapshot-dir` become summary warnings and stay bar-only.

## How lookahead is avoided

- Dataset query: `available_time <= as_of`.
- Replay: reject bars/CA/sessions with `event_time > as_of`.
- Clock: monotonic UTC.
- Sort primary key: `event_time`.

```text
event_time <= as_of
```

For bars and corporate actions that is the same as
`available_time <= as_of`.

## Events

| Kind | Role |
|------|------|
| `replay_started` | Window `start_time` / `end_time` / `as_of` |
| `market_session` | Local calendar day (informational) |
| `corporate_action` | Stored CA; prices unchanged |
| `market_bar` | One PIT-visible daily bar |
| `replay_finished` | Counts and timeline bounds |

There are no order, signal, or portfolio events.

## Sources

### Database

```python
replay = create_daily_bar_replay(
    session,
    request,
    include_corporate_actions=True,
    include_sessions=True,
    deterministic_id=True,
)
```

### Snapshot

```python
replay = replay_daily_bars_snapshot("/path/to/snapshot")
```

Bars only. Integrity verification still runs first.

## Script

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --calendar XNYS \
  --include-sessions \
  --include-corporate-actions \
  --audit \
  --deterministic-id
```

## What does not exist

- strategies, signals, indicators-as-signals
- backtesting engine, optimizer, risk engine
- orders, trades, fills, portfolio, positions
- brokers, paper trading, live trading
- HTTP routes beyond `GET /health`
- persisted simulation runs
- ML / LLM runtime, vendor downloads
