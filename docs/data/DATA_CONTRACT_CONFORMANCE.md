# Data-contract conformance reports — Phase 7.1

Offline **conformance reports** check a captured (or synthetic) payload
batch against the vendor-agnostic data source contract. They write
hashed local artifacts and pin those results with a golden regression
matrix.

This is **not a trading system**. It does **not** compute returns, PnL,
Sharpe, drawdown, hit ratio, or exposure. It does **not** download data,
call a vendor, or read credentials.

Package: `quant_platform.data.contracts.conformance`,
`conformance_types`, `conformance_artifacts`, `conformance_integrity`,
`conformance_regression`.

Fixtures: `tests/fixtures/data_contract_conformance/`.

Related: [DATA_SOURCE_CONTRACTS.md](DATA_SOURCE_CONTRACTS.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[CAPABILITY_MATRIX.md](../release/CAPABILITY_MATRIX.md).

No Alembic migration. Expected head remains
`0010_normalized_dataset_catalog`.

## What conformance is

A conformance run:

1. Loads a local JSON batch (or the in-memory fake provider).
2. Reuses the Phase 7.0 validators and `hash_vendor_payload_batch`.
3. Collects validation issues, forbidden trading/performance terms, and
   offline-package violations.
4. Emits a deterministic report (`ok`, counts, issue codes, hashes).
5. Optionally writes relative-path artifacts and a manifest.

Same batch + same contract = same `conformance_hash`. The digest omits
wall-clock, absolute paths, random UUIDs, and secrets.

## Why it is offline

The runner never opens sockets. It does not use `requests`, `httpx`,
`aiohttp`, or `urllib` against a vendor. Tests and scripts refuse
credentials and connection URLs in artifacts. Real vendor modules
(Polygon, Yahoo, Alpaca, …) stay **unimplemented**.

`external_market_data_vendors` remains a **disabled** capability.
`vendor_runtime` is `none`.

## Why it does not calculate returns or PnL

Conformance checks **shape, PIT timestamps, secrets, and forbidden
terms**. It does not score a strategy. A green report means the
payload matched the contract, not that a dataset has edge.

## Why it is not trading

There are no orders, fills, brokers, portfolios, signals, or
strategies in this package. `APP_MODE` stays `research`.

## How to run a report

```bash
make data-contract-conformance
uv run python scripts/run-data-contract-conformance.py --json
uv run python scripts/run-data-contract-conformance.py \
  --fixture-dir tests/fixtures/data_contract_conformance/valid_batch \
  --output-dir /tmp/data-contract-conformance \
  --json
```

Flags:

| Flag | Meaning |
|------|---------|
| `--batch-file` | Local JSON batch file. |
| `--fixture-dir` | Directory with `batch.json` (and optional `request.json`). |
| `--output-dir` | Write report and manifest JSON. |
| `--json` | Print the report. |

Without `--batch-file` or `--fixture-dir`, the script uses the
in-memory fake provider. The script does not print connection URLs.
It does not need PostgreSQL.

Artifacts (relative paths only):

- `data_contract_conformance_report.json`
- `data_contract_conformance_manifest.json`
- `source_payload_batch.json` (optional)

`verify_data_contract_conformance_artifacts(run_dir)` checks hashes,
relative paths, no traversal, no secrets, no token URLs, and flag
coherence. It does not write files.

## How to run regression

```bash
make data-contract-conformance-regression
uv run python scripts/run-data-contract-conformance-regression.py --json
```

Flags:

| Flag | Meaning |
|------|---------|
| `--fixtures-dir` | Case root. Default: `tests/fixtures/data_contract_conformance`. |
| `--output-dir` | Write report and actuals JSON. |
| `--update-expected` | Write actuals for review. Does **not** rewrite `expected.json`. |
| `--json` | Print the report. |

`make research-release-check` runs this matrix (it is in-memory and
fast). It is **not** part of `make quality`. Skip it with
`--skip-data-contract-conformance`.

## Golden cases

| Case | What it pins |
|------|----------------|
| `valid_batch` | ACME bar + split + session; `ok=true`, 0 issues |
| `invalid_time_order` | `available_time == observation_time` → `lookahead` |
| `secret_in_metadata` | `metadata.token` → `secret_in_metadata` |
| `forbidden_term_in_metadata` | “PnL or returns” note → `forbidden_term` |
| `mixed_batch_with_issues` | One valid bar plus one lookahead bar |

Each case has `batch.json`, `request.json`, and `expected.json`.
Fixtures are fictional. They are not vendor data.

Compared fields:

- `conformance_hash`
- `batch_hash`
- issue count and issue codes
- `ok` / `validation_ok` / `forbidden_terms_ok` / `offline_only_ok`

## How to review drift

If a case fails with `conformance_hash_changed` or a count/code change:

1. Run `make data-contract-conformance-regression` or the script with
   `--json`.
2. If the change is intentional, write actuals:

```bash
uv run python scripts/run-data-contract-conformance-regression.py \
  --output-dir /tmp/data-contract-conformance-regression \
  --update-expected
```

3. Read `data_contract_conformance_regression_actuals.json`.
4. Confirm the new hashes, counts, and issue codes. Reject any
   returns/PnL fields, vendor HTTP clients, or secrets.
5. Copy the reviewed values into that case's `expected.json` **by hand**.
6. Re-run the matrix.

The runner never auto-rewrites goldens. `--update-expected` only writes
actuals beside the optional output directory.

## Research status

`make research-status` prints:

- `data_contract_conformance_supported=true`
- `vendor_runtime=none`
- `external_market_data_vendors=disabled`
