# Data source contracts

Vendor-agnostic payload contract for **future** market-data adapters.
This is not a download client.

Related: [ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[DATA_INGESTION.md](DATA_INGESTION.md),
[DATA_CONTRACT_CONFORMANCE.md](DATA_CONTRACT_CONFORMANCE.md).

`APP_MODE` remains **research**. There is no trading, no PnL/returns, and
no brokers in this layer. There are **no** real vendors, **no** internet
calls, and **no** credentials.

Package: `quant_platform.data.contracts`.
Offline fake: `FakeVendorPayloadProvider.load_batch()`.

## What exists

- Typed payloads for daily bars, corporate actions, and market sessions
- Pure validators (no PostgreSQL, no sockets)
- Deterministic batch hash `sha256:<64 hex>`
- In-memory / local-fixture provider for tests

## What does not exist

- Polygon, Alpha Vantage, Yahoo, Nasdaq, Tiingo, IEX, Bloomberg,
  Refinitiv, Interactive Brokers, Alpaca, Binance, Coinbase, or any
  other HTTP/API vendor
- `requests` / `httpx` / `aiohttp` / `urllib.request` in this package
- Automatic downloads, workers, schedulers, or remote caches
- Broker, order, fill, portfolio, or performance fields

Tests for this package stay offline.

## Canonical payload shape

Every captured record has:

| Field | Role |
|-------|------|
| `source_name` | Stable source identity (`offline_fixture`, `local_csv`) |
| `observation_time` | Timezone-aware UTC economic time |
| `available_time` | Timezone-aware UTC knowable-at time |
| `ingestion_time` | Capture wall-clock (audit only; **excluded from hash**) |
| `raw_payload` | Exact received mapping (secrets forbidden, not stored as URLs with tokens) |
| validation issues | Collected by the offline validator |

The batch hash is `payload_hash`. Individual silver mapping is **not**
done here.

### Daily bars (required)

- `symbol` (non-empty)
- `source_name`
- `observation_time` (aware UTC)
- `available_time` (aware UTC, **strictly after** `observation_time`)
- `ingestion_time` (aware UTC)
- `open`, `high`, `low`, `close` (finite, non-negative decimals)
- `high >= low`, and `high`/`low` consistent with open and close
- `volume` omitted or non-negative
- `raw_payload`
- optional `is_correction` / `correction_reason`

### Corporate actions (required)

- `symbol`
- `source_name`
- `action_type`: `split`, `reverse_split`, `dividend`, `symbol_change`,
  `delisting`
- `effective_time` (aware UTC)
- `available_time` (aware UTC; may precede `effective_time`)
- `observation_time` (aware UTC)
- `ingestion_time` (aware UTC)
- `raw_payload`
- optional quantities, `cash_amount`, `currency`, `note`

Dividends stay **informational**. This contract does not adjust prices.

### Market sessions (required)

- `source_name`
- `calendar_code`
- `session_date` (civil date)
- `observation_time` / `available_time` / `ingestion_time` (aware UTC)
- `session_kind`: `open`, `holiday`, `half_session`, `exceptional_close`
- `is_open` matching that kind
- `raw_payload`
- optional `symbol`, `note`

## `available_time` rules

- Daily bars: `available_time > observation_time`. Equal or earlier is
  lookahead and is rejected.
- Naive datetimes are rejected. Offsets are normalized to UTC.
- Corporate actions: announcement can be knowable before the economic
  effect. Do not treat `available_time < effective_time` as bar
  lookahead.
- Replay and dataset `as_of` filters still use `available_time <=
  simulation_time` once rows are in silver. This contract does not
  query PostgreSQL.

## Source identity

- `source_name` is a lowercase identifier: `[a-z][a-z0-9_]{1,62}`.
- Allowed kinds in this phase: `offline_fixture`, `local_csv`.
- Real vendor product names are **rejected** (`polygon`, `yfinance`,
  `alpaca`, and the rest of the forbid-list).
- `source_name` is not a URL and not a credential.
- `DataSourceContract.requires_network` and `requires_credentials`
  must be false. `pit_required` and `capture_raw_payload` must be true.

## Payload hash

`hash_vendor_payload_batch(batch)` returns `sha256:` plus 64 lowercase
hex characters.

The digest includes source identity, contract flags, and canonical
records. It **excludes**:

- wall-clock fields (`ingestion_time`, `created_at`, `now`, …)
- absolute filesystem paths
- secret keys (redacted before hashing; validation still fails if they
  are present)
- caller list order (records are sorted on identity fields; JSON keys
  are sorted)

The hash is the idempotence key for a captured batch. It is not a
performance metric.

## Idempotence

- The same canonical records hash the same, including after reordering.
- A correction is a **new** daily-bar payload with a later
  `available_time` and `is_correction=true`. Do not mutate the previous
  payload.
- Re-running `FakeVendorPayloadProvider.load_batch()` on the same
  in-memory/fixture data must yield the same hash.
- Future silver ingest (not in this phase) must keep bronze raw rows
  and insert new PIT silver rows, never rewrite OHLCV in place.

## Corrections

Corrections follow ingestion rules: new row, later `available_time`,
reason set. This package only validates the payload shape. It does not
write `daily_bars` or `supersedes_*` pointers.

## Rejection rules

The offline validator fails a payload or batch when:

- `symbol` or `source_name` is missing (sessions may omit symbol)
- timestamps are naive or not UTC-convertible
- daily-bar `available_time <= observation_time`
- OHLC is negative, non-finite, or `high < low` (or inconsistent with
  open/close)
- volume is negative
- corporate action lacks a usable `effective_time` / allowed
  `action_type`
- session lacks `session_date` / allowed `session_kind`
- metadata or `raw_payload` contains secret keys (`api_key`, `token`,
  `password`, …)
- a string contains an `http(s)` URL with `api_key` / `token` query
  parameters
- trading or performance terms appear (`trading`, `PnL`, `returns`,
  orders, fills, portfolio, …)
- `source_name` is a real vendor identity
- the contract requires network or credentials

Issues are collected on `VendorPayloadValidationReport`. The fake
provider raises `VendorContractError` when `load_batch()` validation
fails.

## No real vendors / no internet in tests

Unit tests must not:

- call HTTP
- import `requests`, `httpx`, or `aiohttp` from
  `quant_platform.data.contracts`
- read connection URLs into payloads
- ship API keys

Use `FakeVendorPayloadProvider` or local JSON fixtures only.

Release checks fail if a real vendor module appears under
`quant_platform` or if the contracts package grows networking imports.
`external_market_data_vendors` remains a **disabled** capability.

## Conformance reports

Phase 7.1 adds offline conformance reports and a golden regression
matrix. See [DATA_CONTRACT_CONFORMANCE.md](DATA_CONTRACT_CONFORMANCE.md).

```bash
make data-contract-conformance
make data-contract-conformance-regression
```

No HTTP. No vendors. No PostgreSQL. No returns/PnL.
