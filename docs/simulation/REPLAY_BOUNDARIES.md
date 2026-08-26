# Replay boundaries — Phase 3.2

The **replay boundary** is the rule that a simulation stream is a
closed interval on the research timeline: it always begins with
`ReplayStartedEvent` and always ends with `ReplayFinishedEvent`, even
when some facts were already knowable before `start_time`.

This is not a strategy, not a signal, and not a backtest. It only
orders stored market facts.

Details of hashing and issue codes: [REPLAY_AUDIT.md](REPLAY_AUDIT.md).
Producer overview: [DATASET_REPLAY.md](DATASET_REPLAY.md).

## Why `ReplayStartedEvent` is always first

`ReplayStartedEvent` marks the **start of this replay**, not the first
moment any fact existed. A corporate action can have
`available_time < start_time` and still belong in the window because
its `effective_time` falls in `[start_time, end_time]`.

If those facts kept `event_time = available_time`, they would sort
**before** `ReplayStartedEvent`. The clock would move, then the
started bookend would appear late. Phase 3.2 forbids that.

`ReplayFinishedEvent` is the matching close of the stream.

## Pre-known facts

A payload event is **pre-known** when its native PIT (or calendar)
instant is strictly before `start_time`, and the fact is still visible
at `as_of` (`available_time <= as_of`).

Decision (no extra event type):

- Keep `CorporateActionEvent`, `MarketBarEvent`, and `MarketSessionEvent`.
- Set `known_before_start=True`.
- Clamp simulation `event_time` to `start_time`.
- Leave `available_time` unchanged (PIT). There is no
  `original_event_time` field.
- Emit the event **immediately after** `ReplayStartedEvent`.

In-window bars and corporate actions still use
`event_time = available_time` and `known_before_start=False`.

A fact with `available_time > as_of` is never emitted (lookahead).

## `event_time` vs `available_time`

| Field | Meaning |
|-------|---------|
| `available_time` | Earliest the platform treats the fact as knowable (PIT). Never rewritten by the boundary. |
| `event_time` | Instant on the **simulation clock**. For in-window PIT facts this equals `available_time`. For pre-known facts it is `start_time`. |
| `observation_time` / `effective_time` | When the economic observation or action occurred. Not used as `event_time`. |

`event_time >= available_time` always. The replay never sees a fact
before it was knowable.

## Market sessions

`MarketSessionEvent` is a **local static calendar** row. It is not a
vendor point-in-time history and has no separate published-at timestamp.
`event_time` is `session_date` at `open_time` in the calendar timezone
(or midnight local), converted to UTC.

If that instant is before `start_time`, the same pre-known rule applies:
`known_before_start=True` and `event_time = start_time`. `session_date`
is unchanged.

## Canonical order

1. `ReplayStartedEvent` (boundary group 0)
2. Pre-known payload (`known_before_start=True`, group 1)
3. In-window payload, ordered by `event_time` (group 2)
4. `ReplayFinishedEvent` (group 3)

Inside a group, after `event_time`: type priority, then instrument or
calendar code, then observation / effective / `session_date`, then
source / `action_type` / `session_kind`, then a stable id.

Type priority is unchanged: started → session → corporate action →
bar → finished.

## Stream hash

`hash_replay_events` is canonical JSON, format version **2**. It
includes `known_before_start`. It does not include `replay_id`,
wall-clock time, absolute paths, or secrets.

Same input + same code version ⇒ same `stream_hash`.

## Fixtures

Small deterministic JSON streams live in
`tests/fixtures/replay_events/`:

| File | Role |
|------|------|
| `simple_daily_replay.json` | Started, one in-window bar, finished |
| `corporate_action_preknown.json` | Pre-known split after started |
| `calendar_sessions_replay.json` | Local session + bar |
| `correction_replay.json` | PIT restatement bar |

Load with `load_replay_events_json`. They are for tests, not cataloged
replay-run artifacts. Exported runs use `events.jsonl` instead; see
[REPLAY_RUNS.md](REPLAY_RUNS.md).

## What does not exist

- strategies, signals, indicators-as-signals
- backtesting engine, optimizer, risk engine
- orders, trades, fills, portfolio, positions
- brokers, paper trading, live trading
- HTTP routes beyond `GET /health`
- full event streams in PostgreSQL
- ML / LLM runtime, vendor downloads
