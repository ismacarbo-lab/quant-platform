# Research policy interface — Phase 4.2

A **research policy** is an event observer used by the dry-run backtest
engine. It is **not** a `Strategy`, not a signal model, and not an
execution engine.

Package: `quant_platform.backtest.policy_interface`,
`observations`, `policy_registry`, and `policy`.

Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
NoOp: [NOOP_POLICY.md](NOOP_POLICY.md).
Integrity: [BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md).
Policy output reports: [POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md).
Experiments: [BACKTEST_EXPERIMENTS.md](BACKTEST_EXPERIMENTS.md).
Experiment usability: [BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md).

## What ResearchPolicy is

`ResearchPolicy` is a protocol with typed replay hooks:

- `on_replay_started`
- `on_market_session`
- `on_corporate_action`
- `on_market_bar`
- `on_replay_finished`
- `finalize()` → `PolicyRunOutput`

`EventObserver.observe` remains for string kinds and unknown payloads.
The engine dispatches through `apply_research_event`.

## Why it is not a Strategy

A strategy would decide to buy, sell, hold, size, or rebalance. That
would introduce signals, orders, and look-ahead risk. This interface
only **watches** a ready replay stream and records descriptive notes.

Allowed names: `ResearchPolicy`, `EventObserver`, `EventCountingResearchPolicy`.
Forbidden names in this layer: Strategy, Signal, Alpha, Execution,
Order, Portfolio, Trade.

## What it may emit

- `ResearchObservation` (`event_seen`, `session_seen`,
  `corporate_action_seen`, `correction_seen`, `unknown_event`,
  `missing_expected_event`, `policy_note`)
- counters and non-financial descriptive metrics
- warnings / errors
- audit notes in `policy_config` (JSON object, no secrets)

Severity is `info`, `warning`, or `error`. Observations use replay
`event_time` (not wall-clock).

## What it must not emit

buy / sell / hold, signals, weights, targets, orders, trades, fills,
positions, portfolio, cash, PnL, returns, exposure.

The registry and observation constructors reject those words as whole
tokens. `policy_output.json` is checked the same way.

## Registered policies

Static registry only (`get_research_policy`). No plugins, no
entry points, no imports from arbitrary paths.

| Name | Implementation |
|------|----------------|
| `noop` | `EventCountingResearchPolicy` (alias `NoOpBacktestPolicy`). Counts events. Observations off unless `emit_observations=true` in config. |
| `event_counting` | Same class with informational observations enabled. |

Unknown names raise `invalid_policy`. `momentum` and similar names are
rejected.

A Phase 4.4 experiment binds **one** of these names and groups the
resulting dry-runs. Phase 4.5 aggregates those members' observation
reports; it does not add a third policy or a strategy.

`NoOpBacktestPolicy` and `EventCountingBacktestPolicy` remain aliases of
`EventCountingResearchPolicy` for Phase 4.0 compatibility.

## Policy output hash

`hash_policy_output` is SHA-256 of canonical JSON:

- `policy_name`
- `policy_config`
- observation summary (counts by kind, event counts)
- observations sorted by event time, kind, instrument, message

It excludes wall-clock, random UUIDs, absolute paths, and secrets.
Timestamps are UTC with microseconds and `Z`.

`backtest_hash` includes `policy_name`, `policy_config`, and
`policy_output_hash`. Same replay + same policy config ⇒ same hashes.

## Run a NoOp backtest

```bash
uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name noop \
  --register \
  --deterministic-id \
  --json
```

Optional config (JSON object):

```bash
uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name event_counting \
  --policy-config-json '{"note":"audit-only"}' \
  --register
```

Local artifacts now include `policy_output.json` next to `summary.json`
and `manifest.json`. Phase 4.3 adds observation reports and a dedicated
verifier for that file (`report-policy-output.py`,
`verify-policy-output.py`). PostgreSQL stores `policy_config` (JSONB) and
`policy_output_hash` (text, nullable on old rows). Event streams stay
on disk, not in JSONB.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold recommendations
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- dynamic policy plugins
- HTTP routes beyond `GET /health`
- cloud object storage
