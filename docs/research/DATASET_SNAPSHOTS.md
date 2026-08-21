# Dataset snapshots — Phase 2.2

A snapshot is a **local, auditable folder** that records how a research
dataset was built: the PIT request, the bars that entered, the quality
report, content hashes, package version, and git commit when available.

This is not a backtester, not object storage, and not an HTTP API. Snapshots
live on disk next to the operator. No S3/GCS/Azure, no vendors, no trading.

Package: `quant_platform.research.snapshots` (plus `snapshot_types`). No new
database tables.

## What a snapshot stores

Under `--output-dir` (created if missing):

| File | Contents |
|------|----------|
| `daily_bars.csv` | PIT-visible daily bars from `get_daily_bars_dataset` |
| `quality.json` | Quality report with `generated_at` set to snapshot `created_at` |
| `manifest.json` | Request, counts, hashes, relative artifact names, git commit |

The manifest includes:

- serialized dataset request (`as_of`, range, filters)
- quality request extras (`strict_calendar`, `long_gap_open_sessions`)
- `row_count` / `instrument_count` (unique instruments **in the bar file**)
- quality `error_count` / `warning_count` / `info_count`
- `content_hash`, `quality_hash`, `manifest_hash`
- `package_version`, optional `git_commit`
- `created_at`, optional `notes`

## What it does not store

- `DATABASE_URL`, passwords, tokens
- absolute local paths (artifacts are filenames only)
- adjusted prices, signals, or strategy output
- cloud object keys or cryptographic signatures beyond SHA-256 hashes

Corporate actions are **not** copied into `daily_bars.csv`. They appear in
`quality.json` (visible, not applied). See hashes below.

## Why `as_of` is mandatory

A snapshot without `as_of` could not say which corrections were knowable.
`build_dataset_snapshot_request` reuses the dataset request rules: naive
timestamps and missing `as_of` fail.

## How hashes are calculated

All hashes are SHA-256 over compact canonical JSON (`sort_keys=True`,
separators `,:`), prefixed with `sha256:`.

**`content_hash`** — daily bars only (hash format version 1):

- rows sorted by symbol, exchange, instrument id, observation time, source
- timestamps as UTC with microseconds and a trailing `Z`
- decimals quantized to 8 places (same scale as silver `Numeric`)
- includes `is_correction`, `correction_reason`, `ingestion_run_id`
- **does not** include corporate actions, quality issues, or file paths

**`quality_hash`** — the quality report mapping **excluding** `generated_at`
by default, so two snapshots of the same database match even if they were
taken at different wall-clock times. Corporate actions that were visible at
`as_of` are inside this hash. Pass `include_generated_at=True` only when you
intentionally pin the stamp.

**`manifest_hash`** — canonical JSON of the manifest **without** the
`manifest_hash` field itself. It changes when `created_at` or `snapshot_id`
changes; use `content_hash` to compare dataset bytes.

## Script

```bash
uv run python scripts/create-dataset-snapshot.py \
  --symbol AAPL \
  --exchange XNAS \
  --start 2024-01-01T00:00:00Z \
  --end 2024-12-31T00:00:00Z \
  --as-of 2025-01-02T00:00:00Z \
  --calendar XNAS \
  --output-dir ./artifacts/snapshots/aapl-xnas-2024
```

`--as-of` and `--output-dir` are required. The script does not print
`DATABASE_URL`. Git metadata is `git rev-parse HEAD` in this repository only;
it does not commit, push, or use `/home/isma`'s accidental git directory.

Python:

```python
from quant_platform.research import (
    build_dataset_snapshot_request,
    create_daily_bars_snapshot,
)

request = build_dataset_snapshot_request(
    as_of=as_of,
    start_time=start,
    end_time=end,
    symbols=["FICT"],
)
result = create_daily_bars_snapshot(session, request, output_dir)
print(result.manifest.content_hash)
```

## How to reproduce a dataset

1. Keep PostgreSQL at the same silver rows (or reload the same local CSVs).
2. Re-run the request stored in `manifest.json` → `dataset_request`.
3. Compare `content_hash`. If it matches, the bars are the same.

`git_commit` and `package_version` tell you which code produced the original
folder. Uncommitted working-tree edits are **not** hashed.

## Current limitations

- Snapshots are directories, not a catalog table.
- Quality JSON uses the dataset calendar the same way quality reports do
  (diagnostics; holiday bars stay visible in the report). The CSV follows
  `get_daily_bars_dataset` (holiday bars dropped if `calendar_code` is set).
- `get_git_commit()` returns `None` when git is missing or cwd is not a repo.
- No cloud upload, no signature besides SHA-256.

## Tests

```bash
uv run pytest -m "not postgres"    # hashes, manifest, git helper
uv run pytest -m postgres          # real snapshot folders + PIT hash change
```

## What does not exist

- backtesting, strategies, signals, portfolio, risk, execution, brokers
- paper/live trading, ML, LLM runtime, vendor downloads
- HTTP snapshot routes (still `GET /health` only)
- S3/GCS/Azure, workers, queues, dashboards
