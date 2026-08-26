# Replay runs — Phase 3.3

A **replay run** is one exported, auditable execution of dataset replay.
It is still **data simulation**: ordered market events, not a backtest.

Phase 3.2 produces an in-memory stream plus an audit report. Phase 3.3
writes that stream to **local artifacts** and stores **metadata only** in
PostgreSQL so runs can be listed, compared, and verified later.

Package: `quant_platform.simulation` (`run_types`, `artifacts`,
`run_catalog`, `run_integrity`).
Table: `simulation_replay_runs`. Alembic revision `0006_replay_runs`.

Related: [DATASET_REPLAY.md](DATASET_REPLAY.md),
[REPLAY_AUDIT.md](REPLAY_AUDIT.md),
[REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md),
[BACKTEST_READINESS.md](BACKTEST_READINESS.md).

## What a replay run is

One folder of local files plus an optional catalog row:

1. Replay a PIT dataset (from PostgreSQL or a snapshot).
2. Audit the stream (`boundary_ok`, counts, issues).
3. Write `events.jsonl`, `audit.json`, `summary.json`, `manifest.json`.
4. Optionally register hashes, counts, and compact audit JSON in PostgreSQL.

The catalog does **not** store the event stream. Events stay on disk.

## Artifacts

Written under `--output-dir` (created if missing; existing files with
these names are overwritten; other files are not deleted or moved):

| File | Contents |
|------|----------|
| `events.jsonl` | One canonical JSON object per event, UTC `Z` timestamps, decimals as strings |
| `audit.json` | Full `ReplayAuditReport` including issue list |
| `summary.json` | `ReplaySummary` (simulation timeline, not wall-clock) |
| `manifest.json` | Run metadata, relative artifact paths, `stream_hash`, `manifest_hash` |

Rules:

- artifact paths in the manifest are **relative** (`events.jsonl`, …)
- no absolute paths, no `..`, no `DATABASE_URL` or connection strings
- JSON is stable (sorted keys)
- wall-clock `created_at` is **not** part of `stream_hash`

There is no CSV event dump in this phase. JSONL is the event artifact.

## PostgreSQL metadata

`simulation_replay_runs` stores:

- `replay_id` (unique), `stream_hash`, `manifest_hash` (unique)
- `source_type` (`database` or `snapshot`)
- optional `dataset_snapshot_id` / `dataset_content_hash` (ids/hashes, not paths)
- `package_version`, optional `git_commit`
- `created_at` (from the manifest) and `registered_at` (first insert)
- request window (`as_of`, `start_time`, `end_time` when present in request JSON)
- counts (events, market/session/CA, pre-known, warnings, errors)
- `boundary_ok`, `is_reproducible`, `is_usable`
- `request` JSONB, compact `audit_summary` JSONB, `artifacts` JSONB
- optional `notes`

It does **not** store:

- full event rows
- full audit issue lists (those stay in `audit.json`)
- `DATABASE_URL`, passwords, tokens
- absolute local paths (the run folder is not copied)
- cloud object keys

`dataset_snapshot_id` is optional text copied from a snapshot
`manifest.json` when replaying `--snapshot-dir`. There is no foreign key
to `dataset_snapshots`.

## `stream_hash` vs `manifest_hash`

| Hash | Covers | Stable across re-exports? |
|------|--------|---------------------------|
| `stream_hash` | Canonical event sequence (format v2) | Yes, for the same events. Compare **streams** with this. |
| `manifest_hash` | Manifest payload **excluding** `manifest_hash` itself | No. It changes with `replay_id`, `created_at`, notes, package version, git commit. Compare **this export** with this. |

`stream_hash` never includes wall-clock time or `replay_id`.
`manifest_hash` does include `created_at` and `replay_id`.

Use `--deterministic-id` when you want a stable `replay_id`. The default
is UUID4. Even with a deterministic id, a new export still gets a new
`created_at` and therefore a new `manifest_hash`.

## Usable vs reproducible

| Flag | Meaning |
|------|---------|
| `is_reproducible` | Hashes look like `sha256:<64 hex>`, artifact paths are relative, counts are non-negative, no secret-like markers. Invalid manifests are **rejected**, not stored as `false`. |
| `is_usable` | Reproducible **and** `error_count == 0` **and** `boundary_ok`. Warnings do not block usability. |

`--usable-only` keeps `is_usable=true`. `--boundary-ok` keeps
`boundary_ok=true`.

## Duplicate policy

- **upsert by `replay_id`**: registering the same id again updates metadata
  (`catalog=update`) and keeps the original `registered_at`
- **unique `manifest_hash`**: the same canonical manifest cannot be stored
  under a second `replay_id` (`catalog_conflict`)

Two exports of the same stream at different wall-clock times are two
catalog rows (different `manifest_hash`). Compare them with `stream_hash`.

## Register a run

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-replay \
  --register \
  --notes "fixture run" \
  --deterministic-id \
  --json
```

`--output-dir` writes the four local files. `--register` also upserts
catalog metadata and prints `catalog=insert` or `catalog=update`.
`--register` without `--output-dir` is an error. The script does not
print `DATABASE_URL`.

Python:

```python
from quant_platform.simulation import (
    audit_replay,
    register_replay_run,
    write_replay_run_artifacts,
)

report = audit_replay(replay.events, as_of=replay.summary.as_of)
result = write_replay_run_artifacts(replay, report, output_dir)
register_replay_run(session, result.manifest)
```

`base_path` on `register_replay_run` is accepted and discarded. Absolute
directories are never stored.

## List runs

```bash
uv run python scripts/list-replay-runs.py --usable-only --json
uv run python scripts/list-replay-runs.py --stream-hash sha256:…
uv run python scripts/list-replay-runs.py --source-type snapshot --boundary-ok
```

Filters: `--stream-hash`, `--usable-only`, `--boundary-ok`,
`--source-type`, `--dataset-snapshot-id`. Default output is a TSV-like
table; `--json` prints catalog mappings.

`compare_replay_runs(run_a, run_b)` reports whether stream/manifest
hashes match and deltas for event/error/warning/pre-known counts.
`diff_replay_runs` adds field-level items and a verdict (`identical`,
`same_stream`, `different`). See [BACKTEST_READINESS.md](BACKTEST_READINESS.md).

```bash
uv run python scripts/compare-replay-runs.py --left ID_A --right ID_B
```

## Verify artifacts

```bash
uv run python scripts/verify-replay-run.py --run-dir /tmp/fixt-replay
```

Read-only. Checks that the four files exist, paths are relative and stay
inside the folder, hashes look valid, `manifest_hash` matches the
canonical payload, `stream_hash` can be recomputed from `events.jsonl`,
and counts match the JSONL. It does not write files or talk to
PostgreSQL unless you call `verify_registered_replay_run` in Python.

## Backtest readiness

A registered run is **not** a backtest. The readiness gate decides
whether artifacts and catalog metadata are fit for a **future** engine:

```bash
uv run python scripts/check-replay-readiness.py \
  --replay-id <replay_id> \
  --base-dir /tmp/fixt-replay
```

Details: [BACKTEST_READINESS.md](BACKTEST_READINESS.md).
Dry-run engine (NoOp, no orders): [BACKTEST_ENGINE.md](../backtest/BACKTEST_ENGINE.md).

## Why this is not backtesting

A replay run records **what the data stream was**. It does not:

- generate signals or run a strategy
- hold a portfolio or positions
- place orders, fills, or trades
- talk to a broker
- optimize, train models, or call an LLM

Those packages still do not exist.

## What does not exist yet

- strategies, signals, indicators-as-signals
- real investment policies, optimizer, risk engine
- orders, trades, fills, portfolio, positions
- brokers, paper trading, live trading
- HTTP routes beyond `GET /health`
- event rows in PostgreSQL
- cloud storage (S3/GCS/Azure)
- ML / LLM runtime, vendor downloads
