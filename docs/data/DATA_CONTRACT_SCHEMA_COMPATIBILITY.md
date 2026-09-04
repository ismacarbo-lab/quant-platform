# Data-contract schema compatibility — Phase 7.5

Offline **JSON schema export** and a pinned **compatibility baseline**
for the vendor-agnostic data source contracts. The goal is to detect
incompatible contract changes before any future adapter exists.

This is **not a trading system**. It does **not** compute returns, PnL,
Sharpe, drawdown, hit ratio, or exposure. It does **not** download data,
call a vendor, or read credentials.

Package: `quant_platform.data.contracts.schema_export`,
`schema_compatibility`, `schema_types`.

Fixtures: `tests/fixtures/data_contract_schemas/`.

Related: [DATA_SOURCE_CONTRACTS.md](DATA_SOURCE_CONTRACTS.md),
[DATA_CONTRACT_CONFORMANCE.md](DATA_CONTRACT_CONFORMANCE.md),
[CONTRACT_PAYLOAD_INTAKE.md](CONTRACT_PAYLOAD_INTAKE.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[CAPABILITY_MATRIX.md](../release/CAPABILITY_MATRIX.md).

No Alembic migration. Expected head remains
`0010_normalized_dataset_catalog`.

## What the schema baseline is

`build_contract_schema_bundle()` introspects local dataclasses and emits
a deterministic JSON bundle for:

- `DataSourceContract`
- `VendorDailyBarPayload`
- `VendorCorporateActionPayload`
- `VendorMarketSessionPayload`
- `VendorPayloadBatch`
- `DataContractConformanceReport`
- `DataContractConformanceManifest`

Each definition records `schema_name`, `schema_version`, `fields`,
`required_fields`, `enum_values`, and a `type_repr` per field. The
bundle hash is `sha256:<64 hex>`. Same contract definitions produce the
same hash. The digest omits wall-clock, absolute paths, random UUIDs,
and secrets.

The pinned fixture `current_baseline.json` is that bundle, copied by
hand after review. `expected_compatibility.json` records current versus
current: `compatible`, zero issues.

## How to export schemas

```bash
make data-contract-schema-export
uv run python scripts/export-data-contract-schemas.py --json
uv run python scripts/export-data-contract-schemas.py \
  --output-dir /tmp/data-contract-schemas \
  --json
```

`--output-dir` writes relative-path artifacts:

- `data_contract_schema_bundle.json`
- `data_contract_schema_manifest.json`

No PostgreSQL. No HTTP. No vendors.

## How to review compatibility

```bash
make data-contract-schema-compatibility
uv run python scripts/check-data-contract-schema-compatibility.py --json
uv run python scripts/check-data-contract-schema-compatibility.py \
  --baseline-file tests/fixtures/data_contract_schemas/current_baseline.json \
  --write-current /tmp/data-contract-schemas-current \
  --json
```

`--fail-on-potentially-breaking` is true by default. Use
`--no-fail-on-potentially-breaking` only while inspecting a drift
report. The checker never rewrites the baseline.

Included in `make research-release-check`. Not in `make quality`.

## Compatible changes

These do **not** emit issues:

- adding an optional field (constructor default present)
- adding an enum value that does not remove an existing value and does
  not tighten validation

Current versus current must stay `compatible` with zero issues.

## Potentially breaking changes

These set `compatibility_status=potentially_breaking`:

- removing a field
- changing a field `type_repr`
- making a previously optional field required
- adding a new required field
- removing an enum value
- removing a schema (including a rename, which looks like a removal)
- changing the major schema version without a dedicated ADR

Rules are intentionally simple. This is not SemVer and does not parse
ADRs. A later phase may refine the checker; do not treat a green
compatibility report as permission to ship a vendor adapter.

## How to update the baseline

1. Export the live bundle (`--output-dir` or `--json`).
2. Run the compatibility checker and read the issue codes.
3. Confirm the change is intentional. Reject vendor HTTP clients,
   credentials, returns/PnL fields, and secrets.
4. Copy the reviewed bundle JSON into
   `tests/fixtures/data_contract_schemas/current_baseline.json` **by
   hand**.
5. Keep `expected_compatibility.json` as current versus current
   (`compatible`, `issue_count=0`) unless the review process itself
   changes.
6. Re-run `make data-contract-schema-compatibility`.

The export script never auto-rewrites goldens.

## Why it does not integrate vendors

The baseline describes **local types**. There is still no Polygon,
Alpha Vantage, Yahoo, Nasdaq, Tiingo, IEX, Bloomberg, Refinitiv,
Interactive Brokers, Alpaca, Binance, Coinbase, or any other HTTP
client. `external_market_data_vendors` stays disabled.

## Why it does not call internet

Introspection reads Python dataclasses in-process. Scripts do not
import `requests`, `httpx`, `aiohttp`, or `urllib` for vendors, and
they do not open sockets. Unit tests stay offline.

## Why it does not calculate returns or PnL

Schema export lists field names and types. It does not value a
portfolio, compute returns, Sharpe, drawdown, hit ratio, or exposure.
Those capabilities remain disabled.

## Why it is not trading

There are no strategies, signals, orders, fills, brokers, or
paper/live modes in this layer. `APP_MODE` remains `research` only.
This is **not a trading** control and not a go-live signal.

## Research status

`make research-status` prints:

- `data_contract_schema_baseline_supported=true`
- `data_contract_schema_compatibility_status=compatible`
- `contract_payload_intake_supported=true`
- `vendor_runtime=none`
- `external_market_data_vendors=disabled`
