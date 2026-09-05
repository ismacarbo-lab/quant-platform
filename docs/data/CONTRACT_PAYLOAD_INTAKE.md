# Contract payload intake — Phase 8.0

Offline **intake bridge** from a vendor-agnostic `VendorPayloadBatch`
(synthetic JSON or `FakeVendorPayloadProvider`) onto the existing
research ingestion layer.

This is **not vendor integration**. It does **not** download data, open
sockets, or call Polygon, Yahoo, Alpaca, or any other provider. It does
**not** compute returns, PnL, Sharpe, drawdown, or any performance
metric. It is **not trading**.

Package: `quant_platform.data.contracts.intake`, `intake_types`,
`intake_artifacts`, `intake_integrity`, `intake_regression`.

Fixtures: `tests/fixtures/contract_payload_intake/`.

Related: [DATA_SOURCE_CONTRACTS.md](DATA_SOURCE_CONTRACTS.md),
[DATA_CONTRACT_CONFORMANCE.md](DATA_CONTRACT_CONFORMANCE.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[DATA_INGESTION.md](DATA_INGESTION.md),
[CAPABILITY_MATRIX.md](../release/CAPABILITY_MATRIX.md).

No Alembic migration. Expected head remains
`0010_normalized_dataset_catalog`. No new tables.

## What the bridge does

1. Load a local JSON batch or the in-memory fake provider.
2. Run the existing **conformance** report (PIT, secrets, forbidden
   terms, offline contract).
3. Reject the whole batch unless conformance is `ok` (unless
   `allow_invalid=true`, which still **does not write** PostgreSQL).
4. Map accepted daily bars, corporate actions, and market sessions to a
   deterministic **intake plan** (counts, payload hashes, issues).
5. Optionally write through the **existing** bronze/silver repositories
   when `--write-db` is set.
6. Write relative-path artifacts: plan, report, manifest.

Default is **dry-run**: validate, plan, artifacts; **no INSERT**.

## Why it is offline

The runner never opens sockets. It does not use `requests`, `httpx`,
`aiohttp`, or `urllib` against a vendor. There is no credential or
token environment variable. Real vendor modules stay unimplemented.
`external_market_data_vendors` remains **disabled**. `vendor_runtime`
is `none`. `contract_payload_intake_default` is `dry_run`.

## Dry-run by default

`scripts/run-contract-payload-intake.py` and
`build_contract_payload_intake_plan` do not touch PostgreSQL.

`--write-db` is the only way the CLI writes. `request.json` cannot
silently enable writes; the CLI flag must be present. The library
function `execute_contract_payload_intake` requires
`request.write_db=True` and raises `write_db_required` otherwise.

`--write-db` uses the existing `DATABASE_URL` via settings. Scripts
never print the URL.

## How PIT is conserved

Daily bars keep:

- timezone-aware UTC `observation_time`
- timezone-aware UTC `available_time` with `available_time > observation_time`
- `source_name`
- `payload_hash` (`sha256:<64 hex>` on the plan; 64-hex digest in bronze)

A later `available_time` is a **new PIT version**. Existing
`daily_bars` rows are never updated. `ON CONFLICT DO NOTHING` on
`uq_daily_bars_pit` skips duplicates. Correction pointer columns are
out of scope for this bridge (`insert_daily_bars` still stores
`is_correction=false`).

## How raw capture is preserved

On `--write-db`, each planned record is written to
`raw_ingestion_records` **before** silver insert, using
`redact_payload_secrets` and `payload_sha256`, same as CSV ingest.
Invalid batches never create an ingestion run.

## What is inserted

When `--write-db` and the plan is `ok`:

| Payload | Silver destination | Idempotence |
|---------|--------------------|-------------|
| daily bar | `daily_bars` | PIT unique key; skip if present; **no UPDATE** |
| corporate action | `corporate_actions` | skip if the same instrument/type/effective/available already exists (no unique constraint added) |
| market session | `market_sessions` | skip if `(calendar_id, session_date)` exists; **no UPDATE** of an existing session |

Data sources are created with vendor label `offline_contract` only when
the name is new. Existing `data_sources` rows are reused without
changing `vendor` or `description`. Calendars are reused without
renaming.

Instruments are `upsert_instrument` without passing `name` or
`calendar_id`, so existing instrument identity is not rewritten.

## What stays out

- Real vendor adapters and HTTP clients
- Automatic downloads, workers, schedulers, remote caches
- SQLite
- Mutation or truncate of `daily_bars`
- Strategy, signal, order, fill, portfolio, PnL, returns
- Paper/live trading, brokers, AI runtime
- New HTTP routes

## How to run (dry-run)

```bash
make contract-payload-intake
uv run python scripts/run-contract-payload-intake.py --json
uv run python scripts/run-contract-payload-intake.py \
  --fixture-dir tests/fixtures/contract_payload_intake/valid_dry_run \
  --output-dir /tmp/contract-payload-intake \
  --json
```

## How to write PostgreSQL (explicit)

```bash
uv run python scripts/run-contract-payload-intake.py \
  --fixture-dir tests/fixtures/contract_payload_intake/valid_dry_run \
  --write-db \
  --json
```

Requires `APP_MODE=research` and a reachable PostgreSQL. Re-running the
same batch skips existing PIT bars.

## Regression matrix

```bash
make contract-payload-intake-regression
uv run python scripts/run-contract-payload-intake-regression.py --json
uv run python scripts/run-contract-payload-intake-regression.py \
  --output-dir /tmp/contract-payload-intake-regression \
  --update-expected
```

Goldens live in each case's `expected.json`. `--update-expected` writes
actuals beside `--output-dir`; it does **not** rewrite goldens.

## Evidence bundle (opt-in)

The research evidence bundle can attach this bridge with
`--include-contract-payload-intake`. Default bundles stay unchanged, so
existing hashes remain comparable. Intake inside the bundle is still
**dry-run** unless `--contract-intake-write-db` is also set.

This does **not** integrate a real vendor, call the internet, compute
returns/PnL, or trade. See
[RESEARCH_EVIDENCE_BUNDLE.md](../release/RESEARCH_EVIDENCE_BUNDLE.md).

## Research status

`make research-status` prints:

- `contract_payload_intake_supported=true`
- `contract_payload_intake_default=dry_run`
- `vendor_runtime=none`
- `external_market_data_vendors=disabled`
