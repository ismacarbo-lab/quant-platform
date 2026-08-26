# NoOpBacktestPolicy — not a strategy

`NoOpBacktestPolicy` (alias `EventCountingBacktestPolicy`) is a **test
harness**, not an investment strategy.

It receives replay events in order, increments counters, and records a
stable warning if it sees an unknown `kind`. It does **not**:

- emit BUY/SELL signals
- create orders, fills, or trades
- hold positions or cash
- compute PnL or returns
- call a broker or an LLM

Stored `policy_name` is always `noop`. No other policy is implemented
in this phase.

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

See [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
