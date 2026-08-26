# Dataset snapshot catalog — Phase 2.3

PostgreSQL **metadata catalog** for local research snapshots created in
Phase 2.2. It records how a snapshot was built so you can list, filter, and
compare hashes. It does **not** store OHLCV rows, upload files, or move
folders.

Package: `quant_platform.research.catalog` (plus `catalog_types`).
Table: `dataset_snapshots`. Alembic revision `0005_catalog`.

## What the catalog stores

One row per registered snapshot:

- `snapshot_id` (unique)
- `content_hash`, `quality_hash`, `manifest_hash` (unique)
- `as_of`, observation window, `row_count`, `instrument_count`
- `error_count`, `warning_count`
- `is_reproducible`, `is_usable`
- `dataset_request` JSONB (filters, not bar rows)
- `quality_summary` JSONB (counts + quality hash)
- `artifacts` JSONB (relative filenames only)
- `package_version`, optional `git_commit`, `notes`
- `created_at` (from the manifest) and `registered_at` (first insert)

## What it does not store

- daily bar OHLCV
- quality issue lists or corporate-action rows
- `DATABASE_URL`, passwords, tokens
- absolute local paths (the snapshot folder is not copied)
- cloud object keys

Artifacts stay where `create_daily_bars_snapshot` wrote them. Registering
does not copy, move, or delete files.

## Duplicate policy

Both keys are unique:

- **upsert by `snapshot_id`**: registering the same snapshot again updates
  metadata (`catalog=update`) and keeps the original `registered_at`
- **unique `manifest_hash`**: the same canonical manifest cannot be stored
  under a second `snapshot_id` (`catalog_conflict`)

Two folders of the same bars at different times have different
`snapshot_id` / `manifest_hash` and are two catalog rows. Compare them with
`content_hash`.

## Usable vs reproducible

| Flag | Meaning |
|------|---------|
| `is_reproducible` | Hashes look like `sha256:<64 hex>`, artifact paths are relative and non-empty, counts are non-negative, request timestamps are timezone-aware. Invalid manifests are **rejected**, not stored as `false`. |
| `is_usable` | Reproducible **and** `error_count == 0`. Warnings (missing calendar, gaps) do not block usability. |

`--usable-only` keeps `is_usable=true`.

## Register a snapshot

```bash
uv run python scripts/create-dataset-snapshot.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-snapshot \
  --register
```

Without `--register` the script only writes the local folder (Phase 2.2).
With `--register` it also upserts catalog metadata and prints `catalog=insert`
or `catalog=update`. It does not print `DATABASE_URL`.

Python:

```python
from quant_platform.research import (
    create_daily_bars_snapshot,
    register_dataset_snapshot,
)

result = create_daily_bars_snapshot(session, request, output_dir)
registration = register_dataset_snapshot(session, result.manifest)
```

## List snapshots

```bash
uv run python scripts/list-dataset-snapshots.py --usable-only --symbol FIXT
uv run python scripts/list-dataset-snapshots.py --content-hash sha256:... --json
```

Filters: `--content-hash`, `--snapshot-id`, `--manifest-hash`, `--symbol`,
`--as-of-from`, `--as-of-to`, `--usable-only`.

## Compare snapshots

`compare_dataset_snapshots` / `compare_catalog_snapshots` report whether
content/quality/manifest hashes match, plus `as_of`, window, git commit,
package version, artifact paths, and count deltas. They do not re-read CSV
files. Local file checks are in
[SNAPSHOT_INTEGRITY.md](SNAPSHOT_INTEGRITY.md).

## Migrations

```bash
uv run alembic upgrade head
uv run alembic downgrade 0004_master   # drops catalog + later revisions
```

See [alembic/README.md](../../alembic/README.md).

## Tests

```bash
uv run pytest -m "not postgres"    # validation, flags, comparison
uv run pytest -m postgres          # upsert, filters, Alembic round-trip
```

## What does not exist

- backtesting, strategies, signals, portfolio, risk, execution, brokers
- paper/live trading, ML, LLM runtime, vendor downloads
- HTTP catalog routes (still `GET /health` only)
- S3/GCS/Azure, automatic artifact cleanup, dashboards
- persisted verification status (`last_verified_at` does not exist)
