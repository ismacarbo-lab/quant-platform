# Normalization add-on verification — Phase 6.3

Local research-only verification that operational docs and release
checks match Alembic `0010_normalized_dataset_catalog`. This is **not**
a trading launch, **not** a strategy, and it does **not** compute PnL or
returns.

Related: [COMMANDS.md](COMMANDS.md),
[RESEARCH_RELEASE_CANDIDATE.md](RESEARCH_RELEASE_CANDIDATE.md),
[NORMALIZED_DATASET_CATALOG.md](../research/NORMALIZED_DATASET_CATALOG.md),
[NORMALIZATION_REGRESSION_MATRIX.md](../research/NORMALIZATION_REGRESSION_MATRIX.md).

The freeze tag `v0.1.0-research` was cut at `0009_backtest_experiments`.
Current operational head is `0010_normalized_dataset_catalog`.

## Workspace

- Local: `2026-09-03`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used
- `AI_VENTURE_OS_PROMPTS/` was **not** modified

## Git

| Item | Value |
|------|--------|
| Verified commit (HEAD at verification) | `1530076297d3cbcc4f33d0f985fb2e18cf59f5bc` |
| Subject | Add normalized dataset catalog |
| Working tree | Phase 6.3 docs/status/tests uncommitted (no commit requested) |

Do not treat this note as a new tag.

## Local checks

Run from `/home/isma/invest` with `APP_MODE=research`.

| Check | Result |
|-------|--------|
| `make quality` | ruff/mypy ok; `351 passed`, `144 deselected` (`not postgres`) |
| `make policy-regression` | `18/18 passed`, `errors=0` |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make normalization-regression` | `6/6 passed`, `errors=0` |
| Normalization regression hash | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make research-release-check` | `ok=true`, `errors=0`, `warnings=0`, `alembic=0010_normalized_dataset_catalog` |
| `make research-status` | `final_freeze_ready=true`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `uv run python scripts/normalization-status.py --json` | `ok=true`, `expected_alembic_head=0010_normalized_dataset_catalog`, `dividend_policy=informational only` |

Connection strings were not printed.

## PostgreSQL / Alembic

| Check | Result |
|-------|--------|
| Expected head | `0010_normalized_dataset_catalog` |
| `uv run alembic current` | `0010_normalized_dataset_catalog (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| `normalization-status.py --check-db --json` | `ok=true`, `database_table_present=true`, `database_alembic_head=0010_normalized_dataset_catalog` |
| Public table `normalized_datasets` | metadata-only (no OHLCV columns) |
| Normalized bar table | absent |
| Trading tables | none |
| Isolated `uv run pytest -m postgres` | `144 passed` |

## Evidence bundle opt-in

Command:

```bash
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle-norm \
  --include-normalized-dataset \
  --register-normalized-dataset \
  --deterministic-id \
  --json
```

Operator result on the **shared local PostgreSQL**: `ok=false`,
`error_count=1`. Step `ingest_daily_bars` failed with
`daily bar ingest did not insert research bars` (`ingest_failed`).
Cause: the e2e fixtures were already present; ingest inserted `0` new
rows. Unique constraints were **not** changed to hide this.

Isolated postgres coverage for the same opt-in path:
`test_evidence_bundle_register_normalized_dataset_includes_id` in
`tests/integration/test_evidence_bundle_postgres.py` (`ok=true`,
catalog `normalized_dataset_id` registered, usability `usable=true`).

## Boundaries

- `APP_MODE=research` only
- silver `daily_bars` is not mutated
- `normalized_datasets` stores hashes and counts, not bars
- dividends stay informational only
- no strategies, signals, orders, fills, portfolio, PnL, or returns
- no brokers, paper trading, or live trading
- no AI runtime

## Pending risks

- Catalog usability still needs the local artifact folder (R5b / R8).
- Dividends remain informational; no returns/PnL engine.
- Shared local PostgreSQL can make an operator evidence-bundle ingest
  insert 0 new rows if fixtures were already loaded; isolated
  `pytest -m postgres` remains the CI path.
- Freeze-era reports (`REMOTE_RELEASE_VERIFICATION.md`,
  `POST_TAG_RELEASE_NOTES.md`) still describe `v0.1.0-research` at
  `0009_backtest_experiments`.
