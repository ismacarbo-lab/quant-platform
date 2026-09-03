# Normalized dataset catalog — Phase 6.2

PostgreSQL **metadata catalog** for derived corporate-action-normalized
datasets. It records how a local normalized view was built so you can
list, filter, compare, and re-check usability. It does **not** store
normalized OHLCV rows, raw OHLCV rows, or full event lists.

Package: `quant_platform.research.normalization.catalog` (plus
`catalog_types`).
Table: `normalized_datasets`. Alembic revision
`0010_normalized_dataset_catalog`.

Related: [CORPORATE_ACTION_NORMALIZATION.md](CORPORATE_ACTION_NORMALIZATION.md),
[NORMALIZATION_REGRESSION_MATRIX.md](NORMALIZATION_REGRESSION_MATRIX.md),
[DATASET_CATALOG.md](DATASET_CATALOG.md).

## What the catalog stores

One row per registered derived dataset:

- `normalized_dataset_id` (unique)
- `dataset_hash`, optional `raw_dataset_hash`
- `manifest_hash` (unique)
- `source_type` (`local_artifacts`, `snapshot`, `replay`, `research_dataset`)
- optional `source_snapshot_id` / `source_replay_id` (no required FK)
- `adjustment_mode`, `as_of`, observation window
- `symbol_count`, `bar_count`, `adjusted_bar_count`, `applied_action_count`
- `warning_count`, `error_count`
- `is_reproducible`, `is_usable`
- `artifacts` JSONB (relative filenames only)
- `request` JSONB (filters, not bar rows)
- `report_summary` JSONB (counts, hashes, issue **codes** only)
- `package_version`, optional `git_commit`, optional `notes`
- `created_at` (from the artifact build) and `registered_at` (first insert)

## What it does not store

- normalized OHLCV per row
- raw OHLCV per row
- full corporate-action event payloads
- PnL, returns, portfolio, or any performance series
- `DATABASE_URL`, passwords, tokens
- absolute local paths

Normalized bars stay in the local folder written by
`build-normalized-dataset`. Registering does not copy, move, or delete
those files. Silver `daily_bars` and `corporate_actions` are never
rewritten.

## Duplicate policy

Both keys are unique:

- **upsert by `normalized_dataset_id`**: registering the same id again
  updates metadata (`catalog=update`) and keeps the original
  `registered_at`
- **unique `manifest_hash`**: the same catalog identity cannot be stored
  under a second id (`catalog_conflict`)

`manifest_hash` covers dataset identity, window, mode, counts, relative
artifacts, request, report summary, and source ids. It omits wall-clock,
notes, package version, git commit, and secrets.

## Usable vs reproducible

| Flag | Meaning |
|------|---------|
| `is_reproducible` | Hashes look like `sha256:<64 hex>`, artifact paths are relative, counts are non-negative, timestamps are timezone-aware, metadata has no secrets or forbidden metric language. Invalid rows are **rejected**, not stored as `false`. |
| `is_usable` | Reproducible **and** `error_count == 0`. |

A later usability check also requires local artifact integrity to pass
and catalog hashes to match the files.

`--usable-only` keeps `is_usable=true`.

## Register a normalized dataset

`--register` requires `--output-dir` (already required by the builder).

```bash
uv run python scripts/build-normalized-dataset.py \
  --source-name local_csv \
  --symbol FIXT \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --as-of 2024-01-20T00:00:00Z \
  --adjustment-mode split_only \
  --output-dir /tmp/normalized-fixt \
  --register \
  --deterministic-id \
  --notes "fixture catalog"
```

Without `--register` the script only writes the local folder. With
`--register` it upserts catalog metadata and prints
`catalog=insert` or `catalog=update`. It does not print `DATABASE_URL`.

Optional `--normalized-dataset-id` sets the public id. `--deterministic-id`
derives a stable UUID from `dataset_hash`, `adjustment_mode`, and `as_of`.

## List, verify, compare

```bash
uv run python scripts/list-normalized-datasets.py \
  --dataset-hash sha256:… \
  --usable-only \
  --json

uv run python scripts/check-normalized-dataset-usability.py \
  --normalized-dataset-id ID \
  --base-dir /tmp/normalized-fixt \
  --json

uv run python scripts/verify-normalized-dataset.py \
  --run-dir /tmp/normalized-fixt

uv run python scripts/verify-normalized-dataset.py \
  --normalized-dataset-id ID \
  --base-dir /tmp/normalized-fixt

uv run python scripts/compare-normalized-datasets.py \
  --left ID_A \
  --right ID_B \
  --json
```

Compare verdicts:

| Verdict | Meaning |
|---------|---------|
| `identical` | Same `manifest_hash` |
| `same_dataset` | Same `dataset_hash`, different catalog identity |
| `different` | Different `dataset_hash` |

## Evidence bundle

Default evidence bundles stay unchanged: no catalog id, no extra
normalization step.

Opt-in:

```bash
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --include-normalized-dataset \
  --register-normalized-dataset \
  --deterministic-id
```

When both flags are set the bundle writes `normalized_dataset/`, stores
`normalized_dataset_hash`, registers catalog metadata, stores
`normalized_dataset_id`, and fails if catalog usability does not pass.

## Why this does not calculate returns or PnL

The catalog is a **pointer** to a derived price/volume view. It records
hashes and counts so a later researcher can find the same local folder.
It does not compute period-to-period results, drawdown, Sharpe, or any
portfolio series.

## Why this is not trading

There is no strategy, signal, order, fill, trade, position, portfolio,
broker, paper mode, or live mode. `APP_MODE` remains `research` only.
The table is metadata. Normalized bars are not a trading book.
