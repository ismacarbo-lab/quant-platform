# Dataset replay — Phase 3.3

Replay turns a **point-in-time daily-bar dataset** into a deterministic
sequence of simulation events. Phase 3.1 added optional session and
corporate-action events, a stream hash, and an audit report. Phase 3.2
fixes the **replay boundary**: `ReplayStartedEvent` is always first,
`ReplayFinishedEvent` is always last, and facts known before
`start_time` are marked `known_before_start` instead of sorting before
the started bookend. Phase 3.3 exports a **replay run** (local JSON/JSONL
artifacts) and registers **metadata** in PostgreSQL.

It is **not** backtesting, not a strategy, and not trading.

Package: `quant_platform.simulation`.

Boundary rules: [REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md).
Audit details: [REPLAY_AUDIT.md](REPLAY_AUDIT.md).
Replay runs: [REPLAY_RUNS.md](REPLAY_RUNS.md).
Backtest readiness (compare + gate, not a backtester):
[BACKTEST_READINESS.md](BACKTEST_READINESS.md).

## What replay is

Given a dataset (from PostgreSQL or a local snapshot):

1. emit `ReplayStartedEvent` (always first)
2. emit pre-known payload events (`known_before_start=True`)
3. emit in-window `MarketSessionEvent` rows (local calendar, optional)
4. emit in-window `CorporateActionEvent` rows (stored facts, not applied)
5. emit in-window `MarketBarEvent` rows
6. emit `ReplayFinishedEvent` (always last)
7. return an immutable `DailyBarReplay` plus a `ReplaySummary`

The full list is sorted by the canonical key in
[REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md). Boundary groups force the
bookends to the ends even when a corporate action has
`available_time < start_time`.

Same dataset + same request + same extras + same code version produces
the same event order and the same `stream_hash`. `replay_id` is UUID4
unless `deterministic_id=True`.

`started_at` / `finished_at` on the summary are **simulation timeline**
bounds, not wall-clock times.

Event rows are **not** stored in PostgreSQL. Phase 3.3 writes them to
local `events.jsonl` and keeps hashes/counts in `simulation_replay_runs`.
See [REPLAY_RUNS.md](REPLAY_RUNS.md).

## Event priority

When `event_time` ties **inside the same boundary group**, kinds sort as:

1. `replay_started`
2. `market_session`
3. `corporate_action`
4. `market_bar`
5. `replay_finished`

Then: instrument (or calendar code), observation / effective /
`session_date`, source / `action_type` / `session_kind`, stable id.

## Why `event_time` is usually `available_time`

Bars and corporate actions use **`available_time`**, never
`observation_time` / `effective_time`, as `event_time` **while they are
in-window**. The clock cannot see a close or a split before it was
knowable. Both timestamps stay on the event.

If `available_time < start_time`, replay clamps `event_time` to
`start_time` and sets `known_before_start=True`. `available_time` does
not change.

Session events are **not** PIT market data. Calendars in this platform
are local static fixtures with no separate published-at timestamp.
`event_time` is `session_date` at `open_time` in the calendar timezone,
or midnight local if `open_time` is null, converted to UTC. A session
with `event_time > as_of` is omitted. A session whose native instant is
before `start_time` is pre-known (same clamp + flag).

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
- Replay: reject bars/CA/sessions with `available_time` / native
  `event_time > as_of`.
- Pre-known clamp: `event_time = start_time` and
  `event_time >= available_time`.
- Clock: monotonic UTC.
- Sort: boundary group, then `event_time`.

```text
available_time <= as_of
event_time <= as_of
```

## Events

| Kind | Role |
|------|------|
| `replay_started` | Window `start_time` / `end_time` / `as_of`; always first |
| `market_session` | Local calendar day (informational; not vendor PIT) |
| `corporate_action` | Stored CA; prices unchanged |
| `market_bar` | One PIT-visible daily bar |
| `replay_finished` | Counts and timeline bounds; always last |

Payload kinds may set `known_before_start`. There are no order, signal,
or portfolio events.

## Summary fields

`ReplaySummary` includes `pre_known_event_count`,
`market_event_count`, `session_event_count`,
`corporate_action_event_count`, `first_market_event_time`, and
`last_market_event_time`. `replay_id` is not part of `stream_hash`.

## Fixtures

Reusable JSON streams: `tests/fixtures/replay_events/` (see
[REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md)).

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
  --deterministic-id \
  --json
```

`--audit --json` includes event counts by type, `pre_known_event_count`,
`stream_hash`, boundary status, and first/last market event times. It
does not print `DATABASE_URL`.

Export a local run (and optionally register metadata):

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-replay \
  --register \
  --deterministic-id \
  --json
```

`--register` requires `--output-dir`. List and verify with
`scripts/list-replay-runs.py` and `scripts/verify-replay-run.py`.
Details: [REPLAY_RUNS.md](REPLAY_RUNS.md).

## What does not exist

- strategies, signals, indicators-as-signals
- backtesting engine, optimizer, risk engine
- orders, trades, fills, portfolio, positions
- brokers, paper trading, live trading
- HTTP routes beyond `GET /health`
- full event streams in PostgreSQL (events stay in local JSONL)
- ML / LLM runtime, vendor downloads
