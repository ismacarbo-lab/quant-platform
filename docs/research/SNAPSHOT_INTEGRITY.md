# Snapshot integrity — Phase 2.4

Read-only checks that a local snapshot folder still matches its manifest
and, when asked, the PostgreSQL catalog. Verification does **not** write
files, mutate catalog rows, upload objects, or download data.

Package: `quant_platform.research.catalog_integrity` (plus `integrity_types`).
**No Alembic revision.** Integrity is a report, not a table.

## What is verified

For a snapshot directory:

- `manifest.json` exists and is JSON
- listed artifact paths are relative and stay inside the snapshot root
- listed files exist (`daily_bars.csv`, `quality.json`, `manifest.json`)
- hashes look like `sha256:<64 hex>`
- `manifest_hash` matches a recomputation of the manifest (field excluded)
- `quality_hash` matches `quality.json` with `generated_at` omitted (same
  rule as snapshot creation)
- `content_hash` is recomputed from `daily_bars.csv` using the same
  canonical bar format as `hash_daily_bars_dataset` (UTC microseconds + `Z`,
  8-decimal places, sorted rows)
- `row_count` / `instrument_count` match the CSV
- no `DATABASE_URL`, passwords, or connection-string markers

Against the catalog (optional):

- the `snapshot_id` exists
- a local folder for that id can be found under `--base-dir`
- catalog hashes, counts, `git_commit`, `package_version`, and artifact
  paths match the local manifest

## What is not verified

- PostgreSQL silver rows (this is not a re-query of `daily_bars`)
- corporate actions (they are not in `content_hash`)
- byte-for-byte equality of pretty-printed JSON (hashes use canonical JSON)
- signatures, cloud object keys, or vendor payloads
- strategies, signals, or trading state (none exist)

## Local snapshot

```bash
uv run python scripts/verify-dataset-snapshot.py \
  --snapshot-dir /tmp/fixt-snapshot
uv run python scripts/verify-dataset-snapshot.py \
  --snapshot-dir /tmp/fixt-snapshot \
  --json
```

No database connection. Exit status `1` if any **error** is present.
Warnings do not fail the process.

## Catalog

`--base-dir` may be the snapshot folder itself, or a parent of several
folders. Matching uses `manifest.json` → `snapshot_id` (including a child
named after the id).

```bash
uv run python scripts/verify-dataset-catalog.py \
  --base-dir /tmp/snapshots \
  --usable-only
uv run python scripts/verify-dataset-catalog.py \
  --base-dir /tmp/fixt-snapshot \
  --snapshot-id 11111111-2222-3333-4444-555555555555 \
  --json
```

The catalog is **read**. `registered_at` is not updated. There is no
`--repair` flag in this phase.

## Severities

| Severity | Meaning |
|----------|---------|
| `error` | Broken snapshot or catalog mismatch; `ok=false` |
| `warning` | Reserved; unused for the current checks |
| `info` | Reserved; unused for the current checks |

Codes include `missing_manifest`, `missing_artifact`, `absolute_path`,
`path_escape`, `invalid_hash`, `manifest_hash_mismatch`,
`content_hash_mismatch`, `quality_hash_mismatch`, `secret_like_value`,
`row_count_mismatch`, `instrument_count_mismatch`,
`catalog_manifest_mismatch`, `catalog_entry_missing`,
`missing_snapshot_dir`, `invalid_json`, `invalid_csv`.

If an artifact is missing: restore the folder from backup or recreate the
snapshot with `create-dataset-snapshot.py`. Do not invent CSV rows.

## Compare snapshots

`compare_dataset_snapshots` / `compare_catalog_snapshots` compare metadata
only (hashes, counts, `as_of`, window, git commit, package version, artifact
paths). They do not diff CSV row by row.

## Why rows stay out of PostgreSQL

The catalog stores hashes and counts so you can tell two folders apart
without copying OHLCV into JSONB. Integrity re-reads the local CSV when
you point it at a directory.

## Limitations

- Finding a catalog row on disk requires `--base-dir`; the catalog does
  not store absolute paths.
- Recreating `content_hash` needs a snapshot CSV with the Phase 2.2
  columns. A random vendor file will fail `invalid_csv`.
- Verification is not stored (`last_verified_at` does not exist).
- Extra files in the folder are ignored.

## Tests

```bash
uv run pytest -m "not postgres"
uv run pytest -m postgres
```

## What does not exist

- backtesting, strategies, signals, portfolio, risk, execution, brokers
- paper/live trading, ML, LLM runtime, vendor downloads
- HTTP integrity routes (still `GET /health` only)
- S3/GCS/Azure, automatic repair, moving or deleting snapshot files
