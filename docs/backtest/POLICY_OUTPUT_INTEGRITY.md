# Policy output integrity — Phase 4.3

Read-only checks and summaries for `policy_output.json` produced by a
research policy. This layer does **not** write files, mutate catalog
rows, compute PnL, or emit signals.

Packages:

- `quant_platform.backtest.observation_reports`
- `quant_platform.backtest.policy_output_integrity`
- `quant_platform.backtest.policy_output_types`

Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
Research policy: [RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md).
Backtest folder integrity: [BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md).

**No Alembic revision for this phase.** Catalog columns already exist
from `0008_backtest_policy_metadata`.

Passing these checks does **not** mean a strategy exists.

## What an observation report is

`build_observation_report` summarizes a `PolicyRunOutput` (or
`policy_output.json`) into counts only:

- total observations
- counts by kind and severity
- counts by instrument (when `instrument_id` / `symbol` are present)
- first / last observation (replay `event_time`, not wall-clock)
- unknown events, corrections, corporate actions, sessions
- warning / error counts

It does not generate buy/sell/hold recommendations, weights, targets,
orders, or returns.

## What an observation may contain

Allowed kinds: `event_seen`, `session_seen`, `corporate_action_seen`,
`correction_seen`, `missing_expected_event`, `unknown_event`,
`policy_note`.

Severity: `info`, `warning`, `error`.

Timestamps must be timezone-aware UTC. Messages are descriptive notes
about the replay stream.

## What an observation must not contain

Whole-word tokens such as buy, sell, hold, signal, order, trade, target,
weight, position, portfolio, PnL, return, exposure.

Absolute filesystem paths, secrets (`DATABASE_URL`, passwords), random
UUIDs, and wall-clock stamps are also rejected by integrity.

## How `policy_output.json` is verified

`verify_policy_output` (no database):

- the file exists and is a JSON object
- `policy_output_hash` is SHA-256 of canonical JSON (name, config,
  summary, sorted observations)
- the stored hash matches a recomputation and, when present, the
  sibling `manifest.json`
- kinds and severities are on the allowlist
- timestamps are UTC
- metadata is JSON-safe (`allow_nan=False`)
- summary counts match the observation list
- no secret-like markers, absolute paths, or operative wording

Verification never rewrites the folder.

## How policy outputs are compared

`compare_policy_outputs(left, right)`:

| Verdict | Meaning |
|---------|---------|
| `identical` | Same `policy_output_hash`. |
| `same_counts` | Different hash, same observation / kind / severity / warning / error counts. |
| `different` | Counts or warning/error totals changed. |

This is not a statistical test and not a trading comparison.

## How this affects `usable_result`

`verify_backtest_artifacts` now runs policy-output verification.
`evaluate_backtest_result_usability` requires `policy_output_ok`.

Forbidden operative language or other policy-output integrity **errors**
set `usable_result` to false. That still does **not** mean the policy
was a strategy; it means the research artifact is not intact.

## Why this is not a strategy or a signal

Reports count what the replay showed. They do not decide to open,
close, or size a position. `NoOpBacktestPolicy` / `event_counting`
remain event observers.

## CLI

```bash
uv run python scripts/report-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest
uv run python scripts/verify-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest \
  --json
uv run python scripts/verify-backtest-run.py \
  --run-dir /tmp/fixt-backtest
```

Scripts do not print `DATABASE_URL`. There is no `--repair` flag.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold recommendations, target weights
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
