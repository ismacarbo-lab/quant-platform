# Backtest readiness — Phase 3.4

A **readiness gate** decides whether a registered replay run is fit to
feed a **future** backtesting engine. It does **not** run a backtest.

There is still no strategy, signal, portfolio, order, fill, broker, or
PnL. This phase only compares replay runs and checks that the data
stream is reproducible.

Package: `quant_platform.simulation.readiness` plus
`run_compare` and `constructs`.

Replay artifacts and catalog: [REPLAY_RUNS.md](REPLAY_RUNS.md).
Audit: [REPLAY_AUDIT.md](REPLAY_AUDIT.md).
Boundaries: [REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md).

## What “ready for backtest” means

`ready_for_backtest` is true only when **all** of these hold:

- `APP_MODE=research`
- the `replay_id` is registered
- `stream_hash` and `manifest_hash` look like `sha256:<64 hex>`
- `boundary_ok` is true
- catalog `error_count == 0` (audit had no errors)
- `is_reproducible` and `is_usable` are true
- local artifacts verify without errors (`events.jsonl` stream hash
  matches, paths are relative, counts match)
- no trading constructs (packages, tables, or event kinds)

Warnings (missing snapshot link, unverified snapshot folder, unknown
git commit) **do not** block readiness. They are recorded on the report.

`is_usable` is the catalog flag from Phase 3.3 (reproducible, zero audit
errors, boundary OK). The gate re-checks those fields and **also**
requires a live artifact verify. A usable catalog row whose folder was
deleted is not ready.

## What the gate checks

1. Load `simulation_replay_runs` by `replay_id`.
2. Resolve the run folder under `--base-dir` (the folder itself, a child
   named with the id, or a unique child whose `manifest.json` matches).
3. `verify_registered_replay_run` (hashes, relative paths, JSONL counts).
4. Catalog `boundary_ok`, `error_count`, `is_reproducible`, `is_usable`.
5. Forbidden packages/tables/event kinds (`strategy`, `orders`,
   `trades`, …). Direct children of `quant_platform` only; no markdown
   scan.

## What it does not check

- strategy logic, signals, or indicators-as-signals
- portfolio, positions, orders, fills, execution, brokers
- PnL, returns, or performance metrics
- that a dataset snapshot folder still exists (info/warning only)
- byte-for-byte equality of pretty-printed JSON
- wall-clock `created_at` (use `stream_hash` to compare streams)

## Compare replay runs

`diff_replay_runs` compares catalog/manifest metadata. It does **not**
read `events.jsonl` unless you verify artifacts separately.

It reports:

- `same_stream_hash` / `same_manifest_hash`
- field-level items (`stream_hash`, counts by type, boundary, times,
  git, artifacts, notes, …)
- `verdict`: `identical` (no field diffs), `same_stream` (same stream
  hash, other metadata differs), or `different`

First/last event times are compared when both sides are manifests.
Catalog rows do not store those timestamps; compare them from artifacts
if you need them.

```bash
uv run python scripts/compare-replay-runs.py \
  --left <replay_id_a> \
  --right <replay_id_b> \
  --json
```

## Readiness script

```bash
uv run python scripts/check-replay-readiness.py \
  --replay-id <replay_id> \
  --base-dir /tmp/fixt-replay \
  --json
```

`--base-dir` may be the run folder or a parent of run folders. Exit
status is `0` only when `ready_for_backtest` is true.

Python:

```python
from quant_platform.simulation import (
    diff_replay_runs,
    evaluate_replay_run_readiness,
)

diff = diff_replay_runs(run_a, run_b)
report = evaluate_replay_run_readiness(session, replay_id, base_dir)
```

The scripts do not print `DATABASE_URL`.

## Why backtesting still does not exist

Readiness answers “is this event stream safe to replay again?”. A
backtester would consume that stream to evaluate a strategy. That
engine, and every trading object around it, is still out of scope.

## What the next phase could build

A research backtesting engine that:

- accepts only runs with `ready_for_backtest=true`
- walks the existing event kinds (`replay_started`, sessions, corporate
  actions, bars, `replay_finished`)
- still must not place broker orders in this research platform

That work is not in this phase.
