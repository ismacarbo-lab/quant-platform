# ADR 0005 — Paper-trading pivot with real market data

- Status: accepted
- Date: 2026-10-07
- Supersedes: the operational freeze in
  [ADR 0003](0003-research-mode-freeze.md) (the research tooling itself
  stays and keeps its regression matrices)
- Related: [ADR 0004](0004-vendor-agnostic-data-source-contract.md)

## Context

Through `v0.6.0-research-evidence-intake` the platform was deliberately
research-only: offline fixtures, no vendor client, no strategies, no
PnL, no execution. That freeze proved the data pipeline (PIT daily bars,
bronze/silver capture, corporate actions, normalization, evidence
bundles) is deterministic and auditable.

The owner now wants the platform to be **usable**: load real market
data, test strategies honestly, run them with fictional money, and see
everything in a local dashboard, with a future path to real money.

## Decision

1. **Modes.** `APP_MODE` accepts `research` and `paper`. `live` is still
   rejected by settings validation. Research tooling runs in both modes.
   Only `paper` lets the paper engine write simulated account state.
2. **Real market data.** A `quant_platform.marketdata` adapter downloads
   daily bars, dividends and splits from Yahoo Finance via `yfinance`
   (free, no account, no credentials). It produces a `VendorPayloadBatch`
   with the new `vendor_api` source kind and hands it to the existing
   contract-payload intake, so raw capture, PIT timestamps and
   idempotent silver inserts are reused unchanged. The `contracts`
   package itself still never imports HTTP clients; the adapter is the
   only module allowed to import `yfinance`, and it is imported lazily.
3. **Universe.** Liquid US ETFs spanning asset classes (SPY, QQQ, IWM,
   EFA, EEM, VNQ, TLT, IEF, GLD, DBC) plus BIL as cash proxy. BTC-USD is
   optional. Long-only, daily bars, no leverage, no shorting.
4. **Prices for research.** Normalization gains a `total_return`
   adjustment mode (splits plus reinvested dividends). Silver
   `daily_bars` remain unadjusted.
5. **Strategies.** A `Strategy` interface returns target weights from
   data visible at `as_of` only. Initial implementations have long
   academic evidence: trend (SMA / 10-month), dual momentum, relative
   momentum top-N with trend filter, inverse volatility with a
   volatility target, plus SPY buy-and-hold and 60/40 benchmarks.
6. **Backtests.** A vectorized engine with commission and slippage in
   bps, periodic rebalancing, standard metrics (CAGR, volatility,
   Sharpe, Sortino, max drawdown, Calmar, turnover, positive months) and
   walk-forward in-sample / out-of-sample validation. A promotion rule
   decides which strategy may run in paper: out-of-sample Sharpe above
   the benchmark without a worse maximum drawdown.
7. **Paper trading.** A simulated broker persists accounts, orders,
   fills, positions and equity snapshots in PostgreSQL. A daily run
   downloads data, computes target weights, generates orders and fills
   them at the next open with slippage. Runs are idempotent per account
   and date. A `BrokerAdapter` interface exists so a real broker can be
   plugged in later; none is implemented.
8. **Dashboard.** FastAPI serves a JSON API under `/api` and the built
   React dashboard. Everything binds to localhost.
9. **Guardrails that remain.** No live mode, no real broker SDKs, no
   credentials in the repo, no AI runtime, PostgreSQL only, no silent
   mutation of silver `daily_bars`, research regression matrices stay
   green.

## Honest expectation

Nothing here is "always profitable" or "safe money". The strategies are
chosen because they have decades of evidence, not guarantees. The
backtester charges costs, separates in-sample from out-of-sample, and
always shows the benchmark next to the strategy. If paper trading does
not beat buy-and-hold, the dashboard will say so. Real money is a
separate, future decision that requires another ADR.

## Consequences

- `DISABLED_CAPABILITIES` shrinks to live trading, real brokers, real
  money, leverage, short selling, intraday, AI runtime, SQLite and cloud
  storage. Paper trading, strategies, backtests and yfinance market data
  become enabled capabilities.
- `FORBIDDEN_RUNTIME_PACKAGES` keeps only `live`, `live_trading`, `llm`,
  `rag`. New packages: `marketdata`, `strategies`, `backtesting`,
  `paper`, `api.routes`.
- `yfinance`, `pandas` and `numpy` become runtime dependencies. Broker
  SDKs stay forbidden dependencies.
- New Alembic revisions add `strategy_backtests` and the `paper_*`
  tables. Historical tags are not moved.
- Tests stay offline: the adapter is exercised with recorded fixtures.
