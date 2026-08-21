# Instrument master — Phase 1.4

Research-only instrument identity. This is **not** a vendor security master
and **not** a trading book. There are no live MIC downloads, FIGI/ISIN APIs,
or broker symbol maps.

## What exists

- Surrogate key: `instruments.id` (UUID).
- Natural key: `(symbol, asset_class, exchange_id, currency)` with PostgreSQL
  **`UNIQUE NULLS NOT DISTINCT`** (PG 15+). `symbol` is **not** globally unique.
- Venue table: `exchanges` (`code`, optional `mic`, IANA `timezone`,
  `country`, `currency`).
- Alternate identifiers: `instrument_identifiers`.
- Optional `instruments.calendar_id` → `market_calendars`.

The same ticker may exist on two exchanges, in two asset classes, or in two
currencies. Two rows that omit `exchange_id` and `currency` are the same
instrument.

`upsert_instrument` matches that natural key. It may update `name` and
`calendar_id`. It does not rewrite the key. An unknown `--exchange` code
raises `unknown_exchange` unless the venue was created first (the CSV loader
creates a local stub when `--exchange` is passed).

## Why currency stays in the key

The phase example `(symbol, exchange, asset_class)` is not enough when the
same listing can be quoted in more than one currency. Currency remains part
of uniqueness. Exchange **code** is no longer a free-text column; it is
`exchanges.id` via `exchange_id`.

## Identifier namespaces

Allowed values only (check constraint; no vendor clients):

| Namespace | Meaning here |
|-----------|----------------|
| `isin` | Stored ISIN string, if you type one in. |
| `figi` | Stored FIGI string, if you type one in. |
| `cusip` | Stored CUSIP string, if you type one in. |
| `local_symbol` | The ticker used in a local CSV. |
| `vendor_symbol` | A label from a file you already have. |

`valid_from` / `valid_to` are optional. Unique
`(namespace, value, valid_from)` uses `NULLS NOT DISTINCT`.

## Repository

- `create_exchange()` — insert or return existing `code`
- `create_identifier()` — insert a namespaced alias
- `upsert_instrument(..., exchange_id=)` or `exchange=` (looks up `exchanges.code`)
- `list_exchanges()`, `get_exchange_by_code()`, `list_instrument_identifiers()`

## Fixtures

Small fictional CSVs under `tests/fixtures/`:

- `exchanges.csv`
- `market_calendars.csv` / `market_sessions.csv`
- `corporate_actions.csv`

Loaders: `quant_platform.data.reference_csv`. They do not download calendars
or identifiers.

## What does not exist

- FIGI/OpenFIGI, ISIN, or CUSIP lookups
- Exchange connectivity or official MIC feeds
- Automatic symbol mapping across vendors
- Adjusted prices, split application, or dividend reinvestment
- Strategies, orders, brokers, or portfolios

## Later phases

Vendor identifier enrichment, official calendars, corporate-action
adjustments, and listing status workflows belong in later research phases.
They are not implemented here.
