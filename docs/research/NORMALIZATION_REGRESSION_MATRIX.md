# Normalization regression matrix — Phase 6.1

A **normalization regression matrix** re-runs fictional corporate-action
fixtures through the derived daily-bar view and compares hashes, counts,
and warning codes. It protects the Phase 6.0 layer against accidental
drift.

This is **not** a financial backtest. It does **not** compute returns,
PnL, Sharpe, drawdown, hit ratio, or exposure.

Package: `quant_platform.research.normalization.regression`,
`regression_types`, `regression_artifacts`.

Fixtures: `tests/fixtures/normalization_regression/`.

Related: [CORPORATE_ACTION_NORMALIZATION.md](CORPORATE_ACTION_NORMALIZATION.md),
[POLICY_REGRESSION_MATRIX.md](../backtest/POLICY_REGRESSION_MATRIX.md),
[RESEARCH_EVIDENCE_BUNDLE.md](../release/RESEARCH_EVIDENCE_BUNDLE.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

## What the matrix validates

Each case directory is a closed world:

| File | Role |
|------|------|
| `daily_bars.csv` | Raw OHLCV (dataset-shaped, fixed UUIDs) |
| `corporate_actions.csv` | Stored actions visible to the case |
| `request.json` | `as_of`, range, `source_name`, `adjustment_mode` |
| `expected.json` | Golden hash, counts, warning codes |

The runner assembles the derived dataset **in memory**. It does not open
PostgreSQL and does not rewrite silver `daily_bars`.

Compared fields:

- `dataset_hash`
- `bar_count`
- `issue_count`
- `adjusted_bar_count` (price/volume factor ≠ 1, or applied action ids)
- `actions_applied`
- `expected_warnings` (warning codes such as `dividend_not_adjusted`)

Same fixtures + same `as_of` + same mode = same hash. The digest omits
wall-clock, random UUIDs, absolute paths, and secrets.

## Golden cases

| Case | What it pins |
|------|----------------|
| `split_2_for_1` | 1→2 split restates historical prices and volume |
| `split_4_for_1` | 1→4 split factors |
| `reverse_split_1_for_4` | 4→1 reverse split in `split_and_reverse_split` |
| `dividend_informational` | Dividend warning; prices unchanged |
| `future_action_not_visible` | `available_time` after `as_of` is ignored |
| `multiple_actions_compounded` | Two splits multiply in stable order |

Fixtures are fictional. They are not vendor data.

## How to run it

```bash
make normalization-regression
uv run python scripts/run-normalization-regression.py --json
```

Flags:

| Flag | Meaning |
|------|---------|
| `--fixtures-dir` | Case root. Default: `tests/fixtures/normalization_regression`. |
| `--output-dir` | Write report and actuals JSON. |
| `--update-expected` | Write actuals for review. Does **not** rewrite `expected.json`. |
| `--json` | Print the report. |

Without `--update-expected`, any error fails the process. The script
does not print `DATABASE_URL`. It does not trade.

`make research-release-check` runs this matrix (it is in-memory and
fast). It is **not** part of `make quality`.

## How to review drift

If a case fails with `dataset_hash_changed` or a count code:

1. Run `make normalization-regression` or the script with `--json`.
2. If the change is intentional, write actuals:

```bash
uv run python scripts/run-normalization-regression.py \
  --output-dir /tmp/normalization-regression \
  --update-expected
```

3. Read `normalization_regression_actuals.json`.
4. Confirm the new factors, warnings, and bar counts. Reject any
   returns/PnL fields or buy/sell wording.
5. Copy the reviewed values into that case's `expected.json` **by hand**.
6. Re-run the matrix.

The runner never auto-rewrites goldens. `--update-expected` only writes
actuals beside the optional output directory.

## Evidence bundle opt-in

Default evidence bundles do **not** include a normalized dataset, so
older packs stay comparable.

To attach a verified derived view:

```bash
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --include-normalized-dataset \
  --normalization-adjustment-mode split_only
```

That writes `normalized_dataset/` (CSV, report, manifest), verifies the
artifacts, records `normalized_dataset_hash`, and adds a `normalization`
step. It still does not compute returns or mutate `daily_bars`.

## Why this is not a strategy

The matrix restates OHLCV and records warnings. It does not choose
holdings, emit signals, or score performance. Silver `daily_bars` stay
the PIT audit tape.
