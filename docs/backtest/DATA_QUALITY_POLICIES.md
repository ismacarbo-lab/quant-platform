# Data-quality research policies — Phase 5.0

These policies watch a ready replay stream and emit **descriptive
quality observations**. They are **not** strategies, signals, or
investment decisions.

Package: `quant_platform.backtest.data_quality_policies`.

Interface: [RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md).
Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
Policy output: [POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md).
Experiments: [BACKTEST_EXPERIMENTS.md](BACKTEST_EXPERIMENTS.md).
Regression matrix: [POLICY_REGRESSION_MATRIX.md](POLICY_REGRESSION_MATRIX.md).

**No Alembic revision for this phase.** Catalog columns already exist.

Passing these policies does **not** mean an edge exists.

Output stability is checked by the [policy regression
matrix](POLICY_REGRESSION_MATRIX.md), not by PnL.

## What they observe

| Registry name | Class | Observes |
|---------------|-------|----------|
| `data_quality` | `DataQualityResearchPolicy` | Event counts by kind, bars per instrument, open/holiday/exceptional_close sessions, corporate actions, corrections, unknown events, local `event_time` sequence |
| `coverage` | `CoverageResearchPolicy` | Instruments seen, first/last bar, bar counts, simple date gaps when config provides expected dates or `max_gap_days` |
| `corporate_action_audit` | `CorporateActionAuditPolicy` | Corporate actions by type, pre-known vs in-window, `event_time` / `available_time` |
| `correction_audit` | `CorrectionAuditPolicy` | Correction bars, `is_correction` metadata, pre-known corrections |

They emit only `ResearchObservation` values. They do **not** adjust
OHLCV, pick an alternate correction version, or compute performance.

Existing names `noop` and `event_counting` remain.

## Config (JSON-safe)

Unknown keys are rejected. Negative integers are rejected. Values must
be JSON-serializable (no datetimes).

### `data_quality`

| Key | Type | Default |
|-----|------|---------|
| `emit_event_observations` | boolean | `false` |
| `emit_summary_observations` | boolean | `true` |
| `max_observations` | integer `>= 1` or omit | no cap on per-event notes |

### `coverage`

| Key | Type | Default |
|-----|------|---------|
| `expected_instruments` | list of strings or omit | none |
| `min_bars_per_instrument` | integer `>= 1` or omit | none |
| `expected_dates` | list of ISO dates or omit | none |
| `expected_sessions` | list of ISO dates or omit (merged with `expected_dates`) | none |
| `max_gap_days` | integer `>= 1` or omit | none |

Gap notes use bar `observation_time` dates. This is coverage, not
returns.

### `corporate_action_audit`

| Key | Type | Default |
|-----|------|---------|
| `emit_each_action` | boolean | `false` |
| `action_types` | list of strings or omit | all types |

OHLCV is never rewritten.

### `correction_audit`

| Key | Type | Default |
|-----|------|---------|
| `emit_each_correction` | boolean | `false` |

The policy records that a correction was **seen**. It does not choose
which PIT version to trade.

## What they must not emit

buy, sell, hold, signal, order, trade, target, weight, position,
portfolio, PnL, returns, alpha, recommendation.

They also do not compute drawdown, Sharpe, hit ratio, exposure, cash,
or holdings.

## Observation kinds added

- `data_quality_summary`
- `coverage_summary`
- `coverage_gap`
- `instrument_seen`
- `corporate_action_summary`
- `correction_summary`
- `temporal_consistency_warning`

Earlier kinds (`event_seen`, `session_seen`, `corporate_action_seen`,
`correction_seen`, `unknown_event`, …) remain valid.

## CLI examples

```bash
uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name data_quality \
  --register \
  --deterministic-id

uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-coverage \
  --policy-name coverage \
  --policy-config-json '{"expected_dates":["2024-01-02"],"max_gap_days":3}'

uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-ca \
  --policy-name corporate_action_audit \
  --policy-config-json '{"emit_each_action":true}'

uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-corr \
  --policy-name correction_audit
```

Same names work on experiments:

```bash
uv run python scripts/run-backtest-experiment.py \
  --experiment-name quality-grid \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name data_quality \
  --register \
  --deterministic-id
```

`same replay + same policy config` ⇒ same `policy_output_hash` and
`backtest_hash`. Experiment research reports aggregate the new kinds.
The regression matrix pins those hashes to golden fixtures; it still
does not compute PnL.

Scripts do not print `DATABASE_URL`. They do not trade.

## Why this is still not a strategy

A strategy would decide to buy, sell, hold, or size. These policies only
**describe** the stream: what was seen, what was missing, what looked
inconsistent. There are still no signals, orders, fills, portfolio, or
PnL.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold, target weights
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- dynamic external policy plugins

After changing a quality policy, run
`scripts/run-policy-regression-matrix.py` and review expected hashes
before updating `matrix.json` by hand. See
[POLICY_REGRESSION_MATRIX.md](POLICY_REGRESSION_MATRIX.md).

Release-candidate status and guardrails:
[RESEARCH_RELEASE_CANDIDATE.md](../release/RESEARCH_RELEASE_CANDIDATE.md).
