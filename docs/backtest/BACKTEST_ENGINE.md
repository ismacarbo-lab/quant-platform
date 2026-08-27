# Backtest engine foundation — Phase 4.0 / 4.1 / 4.2 / 4.3 / 4.4 / 4.5 / 5.0 / 5.1

This phase adds an **offline dry-run backtest engine**. It consumes a
registered replay run that already passed the readiness gate, walks the
event stream, and records counts plus hashes.

It is **not** a strategy engine. It does **not** place orders, hold a
portfolio, compute PnL, or talk to a broker.

Package: `quant_platform.backtest`.

Readiness gate: [BACKTEST_READINESS.md](../simulation/BACKTEST_READINESS.md).
NoOp policy: [NOOP_POLICY.md](NOOP_POLICY.md).
Research policy interface:
[RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md).
Artifact integrity and result comparison:
[BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md).
Policy output reports:
[POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md).
Experiments (group dry-runs; not a strategy):
[BACKTEST_EXPERIMENTS.md](BACKTEST_EXPERIMENTS.md).
Experiment usability and aggregated research reports:
[BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md).
Data-quality policies (not strategies):
[DATA_QUALITY_POLICIES.md](DATA_QUALITY_POLICIES.md).
Regression matrix (output stability, not PnL):
[POLICY_REGRESSION_MATRIX.md](POLICY_REGRESSION_MATRIX.md).

## What this backtest is

A controlled loop:

1. Load `replay_id` from `simulation_replay_runs`.
2. Run `evaluate_replay_run_readiness`. Fail if `ready_for_backtest` is
   false.
3. Read `events.jsonl` from the local replay-run folder.
4. Recompute `stream_hash` and require a match.
5. Apply a registered `ResearchPolicy` (`noop` by default, or
   `event_counting`, `data_quality`, `coverage`,
   `corporate_action_audit`, `correction_audit`).
6. Write `summary.json`, `manifest.json`, and `policy_output.json`
   (optional).
7. Optionally register metadata in `backtest_runs`.

The engine references the replay run. It does **not** duplicate the
full event stream into backtest artifacts.

## Why there is still no real strategy

The goal of this phase is a **deterministic harness**: same ready
replay + same policy + same counts = same `backtest_hash`. A real
investment policy would add signals, orders, and look-ahead risk.
Those belong later, behind this gate.

`NoOpBacktestPolicy` exists so the loop can be tested without pretending
that “do nothing” is an alpha model.

## Why there are still no orders or portfolio

Orders, fills, trades, positions, cash, and PnL would be a second
product. This phase only proves that a ready event stream can be
consumed offline under `APP_MODE=research`.

Allowed result fields:

- event / bar (market) / session / corporate-action counts
- started/finished bookends seen
- warnings and errors
- `stream_hash`, `replay_id`, `backtest_hash`

## Hashes

| Hash | Meaning |
|------|---------|
| `stream_hash` | Canonical replay event stream (`sha256:<64 hex>`). |
| `policy_output_hash` | Canonical policy observations + config (no wall-clock). |
| `backtest_hash` | Replay id + stream hash + policy name + policy config + policy output hash + counts + warning/error codes. No wall-clock, no absolute paths, no random UUID. |
| `manifest_hash` | Canonical export of this backtest folder, **including** `created_at` and `backtest_id`. |

Compare **logic** with `backtest_hash`. Compare **this export** with
`manifest_hash`. Two dry-runs of the same stream can share
`backtest_hash` and still differ in `manifest_hash` if `created_at` or
`backtest_id` differs (`same_result` in the Phase 4.1 diff). Recalculate
both hashes with `verify_backtest_artifacts`; do not trust the files
blindly.

`--deterministic-id` derives `backtest_id` from `backtest_hash`. The
default is UUID4 (not part of `backtest_hash`).

## Local artifacts

Written under `--output-dir`:

- `summary.json`
- `manifest.json`
- `policy_output.json`

Not written: a second copy of `events.jsonl`. Point at `replay_id` +
`stream_hash` instead.

Paths in the manifest are relative (`summary.json`, `manifest.json`).
No `DATABASE_URL`, passwords, or absolute directories.

## PostgreSQL catalog

Table: `backtest_runs`. Alembic revisions `0007_backtest_runs` and
`0008_backtest_policy_metadata` (`policy_config` JSONB,
`policy_output_hash` text). Phase 4.4 adds `backtest_experiments`
(`0009_backtest_experiments`) to group those dry-run rows; see
[BACKTEST_EXPERIMENTS.md](BACKTEST_EXPERIMENTS.md). Phase 4.5 adds an
experiment usability gate and research reports without a schema change;
see [BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md).
Phase 5.0 registers data-quality policies without a schema change;
see [DATA_QUALITY_POLICIES.md](DATA_QUALITY_POLICIES.md).

Metadata only (hashes, counts, request/summary JSON, relative artifact
names). No event rows, orders, fills, or positions.

- upsert by `backtest_id`
- unique `manifest_hash`
- conflict if the same `manifest_hash` is owned by another `backtest_id`
- `replay_id` is text, not a foreign key
- `is_usable` is true when the row is reproducible and `error_count == 0`

## Dry-run from the CLI

Requires a registered replay run whose folder is still on disk and
ready:

```bash
uv run python scripts/check-replay-readiness.py \
  --replay-id <replay_id> \
  --base-dir /tmp/fixt-replay

uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name noop \
  --deterministic-id \
  --json
```

Register metadata (`--register` requires `--output-dir`):

```bash
uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --register \
  --deterministic-id \
  --notes "noop dry-run" \
  --json

uv run python scripts/list-backtest-runs.py --replay-id <replay_id> --json
uv run python scripts/list-backtest-runs.py --usable-only --policy-name noop

uv run python scripts/verify-backtest-run.py --run-dir /tmp/fixt-backtest
uv run python scripts/verify-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest
uv run python scripts/report-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest
uv run python scripts/compare-backtest-runs.py --left ID_A --right ID_B --json
uv run python scripts/check-backtest-usability.py \
  --backtest-id ID_A \
  --base-dir /tmp/fixt-backtest

uv run python scripts/run-backtest-experiment.py \
  --experiment-name noop-grid \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name noop \
  --register \
  --deterministic-id \
  --json
uv run python scripts/run-backtest.py \
  --replay-id <replay_id> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-quality \
  --policy-name data_quality \
  --register \
  --deterministic-id
uv run python scripts/check-backtest-experiment-usability.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment
uv run python scripts/report-backtest-experiment.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment \
  --output-dir /tmp/fixt-experiment
```

Python:

```python
from quant_platform.backtest import (
    BacktestRequest,
    compare_backtest_runs,
    register_backtest_run,
    run_backtest_from_replay_run,
)

request = BacktestRequest(replay_id=replay_id, deterministic_id=True)
result = run_backtest_from_replay_run(
    session, request, replay_base_dir, output_dir=output_dir
)
register_backtest_run(session, result.manifest)
```

The engine fails if the readiness gate is red. Scripts do not print
`DATABASE_URL`.

Policy output stability across commits is checked with the
[regression matrix](POLICY_REGRESSION_MATRIX.md), not with PnL.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
