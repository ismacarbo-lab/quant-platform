# Canonical commands — research freeze

Working directory: `/home/isma/invest`.

Do not print secrets. Do not print a live `DATABASE_URL`. Copy
`.env.example` to `.env` for local overrides (gitignored, fictional
placeholders only).

Full narrative: [DEVELOPER_WORKFLOW.md](../development/DEVELOPER_WORKFLOW.md).
Handoff: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md).
Minimal path: [MINIMAL_REPRODUCIBLE_EXAMPLE.md](MINIMAL_REPRODUCIBLE_EXAMPLE.md).

## Setup

```bash
uv python install 3.13
uv sync
cp .env.example .env
```

`APP_MODE` must remain `research`.

## Quality (no PostgreSQL required)

```bash
make quality
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not postgres"
docker compose config
```

## PostgreSQL

```bash
docker compose up -d postgres
uv run python scripts/check-db.py
uv run pytest -m postgres
```

Local Compose uses host port **5434**. Do not fall back to SQLite.

## Alembic

```bash
uv run alembic current
uv run alembic upgrade head
```

Expected head: `0010_normalized_dataset_catalog`.
(`v0.1.0-research` was tagged at `0009_backtest_experiments`.)

## Load sample data

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv
```

No vendors. Local CSV only. Offline payload contracts:
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md).

## Normalized daily bars (derived)

```bash
uv run python scripts/build-normalized-dataset.py \
  --source-name local_csv \
  --symbol FIXT \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --as-of 2024-01-20T00:00:00Z \
  --adjustment-mode split_only \
  --output-dir /tmp/normalized-fixt
uv run python scripts/verify-normalized-dataset.py \
  --run-dir /tmp/normalized-fixt
```

Does not rewrite silver `daily_bars`. Catalog metadata (optional):

```bash
uv run python scripts/build-normalized-dataset.py \
  --source-name local_csv \
  --symbol FIXT \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --as-of 2024-01-20T00:00:00Z \
  --output-dir /tmp/normalized-fixt \
  --register \
  --deterministic-id
uv run python scripts/list-normalized-datasets.py --usable-only --json
uv run python scripts/check-normalized-dataset-usability.py \
  --normalized-dataset-id ID \
  --base-dir /tmp/normalized-fixt
uv run python scripts/compare-normalized-datasets.py --left ID_A --right ID_B
uv run python scripts/verify-normalized-dataset.py \
  --normalized-dataset-id ID \
  --base-dir /tmp/normalized-fixt
```

See
[CORPORATE_ACTION_NORMALIZATION.md](../research/CORPORATE_ACTION_NORMALIZATION.md)
and
[NORMALIZED_DATASET_CATALOG.md](../research/NORMALIZED_DATASET_CATALOG.md).

## Vendor-agnostic data contracts

Offline types, validation, and `FakeVendorPayloadProvider` only. No
HTTP, no credentials, no real vendor client, no trading, no PnL/returns.

```bash
uv run pytest tests/unit/test_data_source_contracts.py
```

See [DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md) and
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md).

## Data-contract conformance

Offline reports against the vendor-agnostic contract. No HTTP, no
credentials, no real vendor, no PostgreSQL, no trading, no PnL/returns.

```bash
make data-contract-conformance
uv run python scripts/run-data-contract-conformance.py --json
uv run python scripts/run-data-contract-conformance.py \
  --fixture-dir tests/fixtures/data_contract_conformance/valid_batch \
  --output-dir /tmp/data-contract-conformance \
  --json
make data-contract-conformance-regression
uv run python scripts/run-data-contract-conformance-regression.py --json
uv run python scripts/run-data-contract-conformance-regression.py \
  --output-dir /tmp/data-contract-conformance-regression \
  --update-expected
```

Does not rewrite `expected.json`. See
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md).
Included in `make research-release-check`. Not in `make quality`.

## Data-contract schema compatibility

Offline JSON schema export and a pinned baseline. No HTTP, no
credentials, no real vendor, no PostgreSQL, no trading, no PnL/returns.

```bash
make data-contract-schema-export
uv run python scripts/export-data-contract-schemas.py --json
uv run python scripts/export-data-contract-schemas.py \
  --output-dir /tmp/data-contract-schemas \
  --json
make data-contract-schema-compatibility
uv run python scripts/check-data-contract-schema-compatibility.py --json
uv run python scripts/check-data-contract-schema-compatibility.py \
  --baseline-file tests/fixtures/data_contract_schemas/current_baseline.json \
  --write-current /tmp/data-contract-schemas-current \
  --json
```

Does not rewrite `current_baseline.json`. See
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md).
Included in `make research-release-check`. Not in `make quality`.

## Contract-payload intake (offline)

Maps a synthetic or fixture `VendorPayloadBatch` onto existing research
ingestion. Dry-run by default. `--write-db` is explicit. No HTTP, no
real vendor, no silent inserts, no trading, no PnL/returns.

```bash
make contract-payload-intake
uv run python scripts/run-contract-payload-intake.py --json
uv run python scripts/run-contract-payload-intake.py \
  --fixture-dir tests/fixtures/contract_payload_intake/valid_dry_run \
  --output-dir /tmp/contract-payload-intake \
  --json
make contract-payload-intake-regression
uv run python scripts/run-contract-payload-intake-regression.py --json
uv run python scripts/run-contract-payload-intake-regression.py \
  --output-dir /tmp/contract-payload-intake-regression \
  --update-expected
```

`--write-db` requires local PostgreSQL and never prints `DATABASE_URL`.
Does not rewrite `expected.json`. See
[CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md).
Included in `make research-release-check`. Not in `make quality`.

## Normalization regression

```bash
make normalization-regression
uv run python scripts/run-normalization-regression.py --json
uv run python scripts/run-normalization-regression.py \
  --output-dir /tmp/normalization-regression \
  --update-expected
```

In-memory; no PostgreSQL. Does not rewrite `expected.json`. See
[NORMALIZATION_REGRESSION_MATRIX.md](../research/NORMALIZATION_REGRESSION_MATRIX.md).
Included in `make research-release-check`. Not in `make quality`.

```bash
uv run python scripts/normalization-status.py
uv run python scripts/normalization-status.py --json
```

Lightweight; no PostgreSQL unless `--check-db`. See
[NORMALIZATION_ADDON_VERIFICATION.md](NORMALIZATION_ADDON_VERIFICATION.md).

## Snapshot

```bash
uv run python scripts/create-dataset-snapshot.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-snapshot \
  --register
```

## Replay

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --include-sessions \
  --include-corporate-actions \
  --output-dir /tmp/fixt-replay \
  --register \
  --deterministic-id \
  --audit \
  --json
```

## Backtest dry-run

```bash
uv run python scripts/run-backtest.py \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name data_quality \
  --register \
  --deterministic-id
```

Not a strategy. No orders.

## Experiment

```bash
uv run python scripts/run-backtest-experiment.py \
  --experiment-name e2e-research-evidence \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name data_quality \
  --register \
  --deterministic-id \
  --json
```

## Policy regression

```bash
make policy-regression
uv run python scripts/run-policy-regression-matrix.py --json
```

Do not auto-rewrite `matrix.json`. Copy expected hashes by hand after
review.

## Release check and status

```bash
make research-status
uv run python scripts/research-status.py --json
make research-release-check
uv run python scripts/research-release-check.py --json
```

Status prints `final_freeze_ready`, `evidence_bundle_available`,
`data_contract_conformance_supported`,
`data_contract_schema_baseline_supported`,
`data_contract_schema_compatibility_status`,
`contract_payload_intake_supported`,
`contract_payload_intake_default`,
`vendor_runtime`,
`external_market_data_vendors`, `alembic_head_expected`, and disabled
capabilities. It does not ping PostgreSQL.

## Evidence bundle

```bash
make research-evidence-bundle
make verify-research-evidence-bundle
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --json
uv run python scripts/verify-research-evidence-bundle.py \
  --bundle-dir /tmp/research-evidence-bundle \
  --json
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --include-normalized-dataset \
  --register-normalized-dataset \
  --json
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --allow-existing-fixture-data \
  --json
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --include-contract-payload-intake \
  --json
```

Not in `make quality`. Needs PostgreSQL. `--include-normalized-dataset`
is opt-in and does not compute returns. `--register-normalized-dataset`
stores catalog metadata only when that opt-in is also set.
`--include-contract-payload-intake` is opt-in, dry-run by default, and
does not call vendors or the internet. `--contract-intake-write-db`
requires that opt-in and does not rewrite `daily_bars`.
`--allow-existing-fixture-data` is off by default. Use it only to re-run
the bundle on a shared database whose existing rows already match the
fixtures. It verifies OHLCV, times, corporate actions, and sessions
before reuse. It does not relax PIT constraints, delete rows, or rewrite
`daily_bars`.

## CI troubleshooting

- Confirm you are in `/home/isma/invest`, not the accidental git at
  `/home/isma`.
- Actions jobs: `quality` (no DB) and `postgres` (service on 5432 inside
  the runner). No GitHub secrets required.
- If **postgres** fails: do not add SQLite. Check the service healthcheck
  and `QUANT_PLATFORM_REQUIRE_POSTGRES=1`.
- If **policy regression** fails: run the matrix locally; review
  observations; update `matrix.json` by hand if the change is intended.
- If **normalization regression** fails: run the matrix locally; review
  factors and warnings; update `expected.json` by hand if intended.
- If **data-contract schema compatibility** fails: export schemas;
  review issue codes; copy `current_baseline.json` by hand if intended.
- If **setup-uv** fails: retry / pin the action; do not weaken gates.
- Never paste passwords or connection URLs into issues or logs.

## Remote verification and tag

See [REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md) and
[POST_TAG_RELEASE_NOTES.md](POST_TAG_RELEASE_NOTES.md).

Annotated tag `v0.1.0-research` exists on `origin`. Do not create another
tag for this freeze.
