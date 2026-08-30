# Corporate-action normalization — Phase 6.0

Research-only derived daily-bar view. Silver `daily_bars` stay untouched.
This is **not** a strategy, **not** a signal, and it does **not** compute
performance.

Package: `quant_platform.research.normalization`.

Related: [CORPORATE_ACTIONS.md](../data/CORPORATE_ACTIONS.md),
[RESEARCH_DATASETS.md](RESEARCH_DATASETS.md),
[NORMALIZATION_REGRESSION_MATRIX.md](NORMALIZATION_REGRESSION_MATRIX.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

## What it normalizes

Given a PIT daily-bar dataset and stored corporate actions visible at
`as_of`, it writes an in-memory `NormalizedDailyBarsDataset` plus optional
local artifacts:

- `normalized_daily_bars.csv`
- `normalization_report.json`
- `normalization_manifest.json`

Each normalized bar keeps raw OHLCV, the derived values, `price_factor`,
`volume_factor`, applied action ids, and a deterministic `trace_id`.

## What it does not normalize

- Dividends (warning `dividend_not_adjusted`; prices unchanged)
- `symbol_change` and `delisting` (informational only)
- Vendor or downloaded actions
- Currency conversion or advanced restatements

`adjustment_mode=informational` or `none` applies no price factors.

## Point-in-time rules

An action is eligible only when `available_time <= as_of`.

A visible action restates a bar only when:

- `instrument_id` matches
- `effective_time > observation_time`

Actions that become knowable after `as_of` are ignored. Actions for other
instruments are ignored.

`get_corporate_actions_for_dataset` still filters `effective_time` to the
observation window (export/replay). Normalization uses
`get_visible_corporate_actions`, which drops that window so a split after
the last bar can still restate earlier rows.

## Split and reverse split

Storage is `quantity_before` / `quantity_after` (share counts), not an
`N:1` string.

A 4-for-1 split is stored as `1` → `4`:

- historical prices multiply by `1/4`
- historical volume multiplies by `4`

A reverse split stored as `4` → `1`:

- historical prices multiply by `4`
- historical volume multiplies by `1/4`

Compound actions multiply factors in a stable order: `effective_time`,
`available_time`, `action_type`, action id.

Default mode is `split_only`. Use `split_and_reverse_split` to include
reverse splits.

## Dividend

Dividends stay informational. The report emits `dividend_not_adjusted`.
Cash amount is not turned into a price factor.

## Why silver is not mutated

`daily_bars` is the PIT audit tape. Normalization is a **derived view**
for research. Re-running the same request must not rewrite history.

## Artifacts and verification

```bash
uv run python scripts/build-normalized-dataset.py \
  --source-name local_csv \
  --symbol FICT \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --as-of 2024-01-20T00:00:00Z \
  --adjustment-mode split_only \
  --output-dir /tmp/normalized-fixt

uv run python scripts/verify-normalized-dataset.py \
  --run-dir /tmp/normalized-fixt
```

Verification checks relative paths, hash format, row counts, secret-like
markers, and forbidden decision/performance wording. It does not repair
files.

`hash_normalized_daily_bars_dataset` is `sha256:<64 hex>`. It covers raw
dataset identity, `as_of`, mode, applied actions, normalized values, and
issues. It omits wall-clock, random ids, and absolute paths.

## Regression matrix

Phase 6.1 pins those hashes with golden fixtures under
`tests/fixtures/normalization_regression/`. Run
`make normalization-regression`. Update `expected.json` by hand after
reviewing actuals. See
[NORMALIZATION_REGRESSION_MATRIX.md](NORMALIZATION_REGRESSION_MATRIX.md).

The evidence bundle can attach this derived view only when
`--include-normalized-dataset` is set. Default bundles stay unchanged.

## Why this is not a strategy

The layer restates prices and volumes. It does not choose holdings, emit
buy/sell notes, or compute PnL or period-to-period results.
