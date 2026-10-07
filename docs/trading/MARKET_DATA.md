# Market data (Yahoo Finance via yfinance)

Module: `quant_platform.marketdata`. Script: `scripts/fetch-market-data.py`
(`make fetch-data`). API: `POST /api/market/fetch`.

## Source

Yahoo Finance through the `yfinance` package: free, no account, no API
key. It is an unofficial feed without SLA (risk R20). Only
`marketdata/providers.py` imports `yfinance`, lazily, so the API and tests
never load it. Tests use `RecordedMarketDataProvider` with CSV fixtures
under `tests/fixtures/marketdata/`.

## Universe

`marketdata/universe.py`: SPY, QQQ, IWM, EFA, EEM, VNQ (risk), TLT, IEF,
GLD (defensive), DBC (risk), BIL (cash proxy). Optional: BTC-USD
(`--include-crypto`). Roles drive the strategies (risk assets, defensive
assets, cash symbol).

## Point-in-time conventions

- Daily bar for session `D`: `observation_time = D 21:00 UTC`,
  `available_time = D 22:00 UTC` (crypto: 23:59 / +31 min). Bars whose
  `available_time` is after "now" are dropped, so an incomplete session is
  never stored.
- Dividends: `effective_time = ex-date 13:30 UTC`, `available_time` one
  hour later, `cash_amount` per share.
- Yahoo prices are already split-adjusted, so **splits are not emitted**
  as corporate actions (they would double-adjust). The raw payload keeps
  the vendor's `Stock Splits` column for audit.
- OHLC bounds are sanitized (`high >= max(open, close)`,
  `low <= min(open, close)`) and flagged in metadata.
- Incremental fetch starts 10 days before the last stored session. A bar
  that differs from the stored one is written as a **correction** (new
  PIT row with `available_time = now`, `correction_reason =
  vendor_restatement`). Nothing is updated or deleted.

## Path into the store

`build_market_data_batch` → `VendorPayloadBatch` (contract
`source_kind = vendor_api`, `requires_network = true`,
`requires_credentials = false`) → `execute_contract_payload_intake`
(bronze raw records, then silver `daily_bars` and `corporate_actions`,
one ingestion run per symbol). `--dry-run` builds the plan only.

## Prices for research and trading

`quant_platform.backtesting.data.load_price_panel` reads the PIT panel at
`as_of` and applies the `total_return` math (dividends reinvested on the
ex-date; same formula as the normalization mode). Strategies see adjusted
closes; paper fills use raw opens/closes.
