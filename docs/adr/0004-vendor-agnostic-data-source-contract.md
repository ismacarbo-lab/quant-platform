# ADR 0004 — Vendor-agnostic data source contract

- Status: accepted
- Date: 2026-09-03

## Context

`quant_platform` ingests **local CSV** into bronze/silver with point-in-time
fields. Releases `v0.1.0-research` and `v0.2.0-research-normalization`
are closed. There is still **no** external market-data client.

A later phase may need a downloadable source. The tempting shortcut is
to pick Polygon, Yahoo, or another API, put a key in `.env`, and fetch
bars in tests. That would:

- bind the research stack to one vendor before PIT, raw capture, and
  idempotence are specified
- pull the internet into unit tests
- mix secrets with fixtures
- blur research evidence with a live feed

[ADR 0003](0003-research-mode-freeze.md) still forbids real vendor
clients and automatic downloads. This ADR does **not** lift that ban.
It only specifies the **contract** a future adapter must satisfy.

## Decision

1. **Do not integrate a real vendor in this phase.** No Polygon, Alpha
   Vantage, Yahoo, Nasdaq, Tiingo, IEX, Bloomberg, Refinitiv,
   Interactive Brokers, Alpaca, Binance, Coinbase, or other HTTP API.
2. **Specify a vendor-agnostic payload contract** (types, validation,
   hashing, fake in-memory provider, documentation).
3. **Point-in-time is mandatory** for every observation:
   `observation_time`, `available_time`, `source_name`,
   `ingestion_time`, `payload_hash`, raw payload capture, and
   validation issues.
4. **Raw capture first.** A future adapter must store the received
   payload (redacted) before mapping to silver. Silver `daily_bars`
   stay the canonical research table; this contract does not rewrite
   them.
5. **Idempotence** is the canonical batch hash (`sha256:<64 hex>`),
   with stable key order, sorted records, and no wall-clock, secrets,
   or absolute paths in the digest.
6. **Traceability** uses `source_name` as a stable identifier
   (`offline_fixture`, `local_csv`), not a product brand and not a URL.
7. **Secrets stay out of the repo.** No API keys, tokens, or connection
   URLs in payloads, tests, or docs.
8. **Rate limits and licensing** are documented future risks. This
   phase does not implement throttling, billing, or license checks.
9. **No trading and no brokers.** The contract is not a market-data
   product for execution. It must not introduce strategies, signals,
   orders, fills, portfolio, PnL, or returns.

## Why not a real vendor yet

- Local CSV and synthetic fixtures already exercise PIT ingestion.
- A live client would force network, credentials, and vendor-specific
  quirks into the research core.
- Corrections, `available_time`, and payload hashes must be defined
  **before** mapping someone else's JSON into `daily_bars`.
- Tests and CI must remain offline.

## PIT requirements

Future adapters must supply timezone-aware UTC timestamps:

| Field | Meaning |
|-------|---------|
| `observation_time` | When the economic observation occurred |
| `available_time` | Earliest time the observation could have been known |
| `ingestion_time` | When this process captured the payload (wall-clock; not hashed) |
| `effective_time` | Corporate-action economic effect (CA payloads) |
| `session_date` | Civil date of a market session |

Daily bars keep the existing silver rule:
`available_time > observation_time` (strict). Corporate-action
`available_time` may precede `effective_time` (announcement before
effect). That is not a daily-bar lookahead violation.

## Consequences

- Package `quant_platform.data.contracts` is offline-only.
- `FakeVendorPayloadProvider.load_batch()` returns synthetic fixtures
  or in-memory payloads. It must not open sockets or read secrets.
- Release capability `vendor_agnostic_data_contracts` is enabled.
- `external_market_data_vendors` stays **disabled**.
- A later ADR is still required before any HTTP vendor adapter,
  scheduler, or credential store.
- `APP_MODE` remains `research` only. Paper and live stay invalid.
- `AI_VENTURE_OS_PROMPTS/` remains a separate product.

## Alternatives rejected

| Alternative | Why not now |
|-------------|-------------|
| Ship a Polygon (or other) client | Chooses a vendor before the contract exists; needs network and secrets. |
| HTTP in unit tests with recorded cassettes | Still a client surface; cassettes hide schema drift and leak URLs. |
| Treat `data_sources.vendor` as a download switch | That column is a local label, not a network client. |
| Skip raw capture and hash only silver rows | Loses audit of what the adapter received. |

## Related

- [DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md)
- [DATA_INGESTION.md](../data/DATA_INGESTION.md)
- [ADR 0001](0001-foundation-architecture.md)
- [ADR 0003](0003-research-mode-freeze.md)
