# NoOpBacktestPolicy — not a strategy

`NoOpBacktestPolicy` is an **alias** of `EventCountingResearchPolicy`
with `policy_name="noop"`. It implements `ResearchPolicy`. Phase 4.0
also exported `EventCountingBacktestPolicy`; that alias remains.

It receives replay events in order, increments counters, and records a
stable warning if it sees an unknown `kind`. With the default NoOp
config it does **not** emit per-event observations. The registered name
`event_counting` uses the same class and emits informational
`ResearchObservation` values.

It does **not**:

- emit BUY/SELL signals
- create orders, fills, or trades
- hold positions or cash
- compute PnL or returns
- call a broker or an LLM

Stored `policy_name` is `noop` or `event_counting`. Both count events.
Neither is a strategy.

## What it counts

| Field | Source |
|-------|--------|
| `event_count` | every observed event, including unknown kinds |
| `market_event_count` | `market_bar` |
| `session_event_count` | `market_session` |
| `corporate_action_event_count` | `corporate_action` |
| `started_event_seen` | at least one `replay_started` |
| `finished_event_seen` | at least one `replay_finished` |

Unknown kinds append `unknown_event:<kind>` to `warnings`. That is a
warning, not an order. `error_count` stays `0` unless a later policy
records errors (none do today).

## Why this exists

The dry-run engine needs something to call inside the event loop. A
real momentum / mean-reversion / ML policy would make this phase a
trading system. Counting events proves:

- the readiness gate is enforced
- `events.jsonl` is consumed in file order
- `backtest_hash` is stable for the same stream and counts

Integrity accepts registered names `noop` and `event_counting`. A
usable result is evidence that the dry-run folder is intact, not that
a strategy exists.

See [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md),
[RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md),
[BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md), and
[POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md).
