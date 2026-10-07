# Capability matrix

Inventory of what `quant_platform` does after the paper-trading pivot
([ADR 0005](../adr/0005-paper-trading-pivot.md)). Implemented does
**not** mean profitable. Disabled and prohibited stay off until a later
ADR.

Historical research tags (`v0.1.0-research` … `v0.6.0-research-evidence-intake`)
describe the frozen research layer; that layer is still here and its
regression matrices still run.

Related: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[RISK_REGISTER.md](RISK_REGISTER.md),
[ADR 0003](../adr/0003-research-mode-freeze.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[ADR 0005](../adr/0005-paper-trading-pivot.md),
[PAPER_TRADING.md](../trading/PAPER_TRADING.md),
[STRATEGIES_AND_BACKTESTS.md](../trading/STRATEGIES_AND_BACKTESTS.md).

## Implemented — research layer

| Capability | What it does | What it is not |
|------------|--------------|----------------|
| Modes | `APP_MODE=research` or `APP_MODE=paper` | Not live |
| Local CSV ingestion | PIT daily bars into PostgreSQL | Not the only data path any more |
| PIT daily bars | `available_time`, corrections as new rows | Not rewritten history |
| Bronze / silver | Raw records + canonical bars | Not gold features |
| Instrument master | Symbol, asset class, exchange, currency | Not a broker account |
| Calendars / sessions | Manual open, holiday, exceptional_close | Not an exchange feed |
| Corporate action store | Facts stored; silver OHLCV unchanged | Not applied in place |
| CA normalization | Derived split / reverse-split / total-return views | Not stored bars |
| Normalized dataset catalog | PostgreSQL metadata table `normalized_datasets` | Not normalized bars in the DB |
| Dataset API / quality / snapshots | `as_of` required; hashed CSV snapshots | Not cloud storage |
| Replay / dry-run backtest / policies | Research observers with golden hashes | Not the strategy engine |
| Evidence bundle | Fixture → release local pack; opt-in intake | Not a performance report |
| Vendor-agnostic data contracts | Payload types, validation, hash, fake provider | Not credentials |
| Contract-payload intake | Plan + optional `--write-db` through PIT ingest | Not silent writes |
| Health endpoint | `GET /health` | — |

## Implemented — trading layer (paper, fictional money)

| Capability | What it does | What it is not |
|------------|--------------|----------------|
| Market data (yfinance) | Downloads daily bars, dividends, splits into the PIT store through contract intake | Not intraday; not a paid vendor; no API key |
| Universe | Liquid US ETFs across asset classes (+ optional BTC-USD) | Not single-stock picking |
| Strategies | Trend, dual momentum, relative momentum top-N, inverse volatility, benchmarks | Not signals from AI |
| Strategy backtests | Vectorized, costs in bps, metrics, walk-forward IS/OOS | Not a guarantee of future returns |
| Portfolio / PnL / returns metrics | CAGR, vol, Sharpe, Sortino, max drawdown, Calmar, turnover | Not real money |
| Paper trading (simulated) | Daily run → target weights → orders → fills at next open with slippage; persisted account | Not a real broker |
| Dashboard API / UI | `/api/*` JSON + local React dashboard | Not exposed to the internet |

## Intentionally disabled

These names exist as **disabled** capabilities in release status:

- live trading
- real brokers
- real money
- leverage
- short selling
- intraday trading
- AI runtime (OpenAI, Anthropic, LangChain, RAG)
- SQLite fallback
- cloud object storage

`APP_MODE=live` fails settings validation.

## Explicitly prohibited (this phase)

Do not add without a new ADR:

- live orders, real brokers, real money, broker credentials
- leverage, margin, short selling, options, futures, intraday
- ML / AI as a trading brain; OpenAI, Anthropic, LangChain, RAG runtime
- silent mutation of silver `daily_bars`
- SQLite substitute for PostgreSQL
- S3 / GCS / Azure object storage
- mixing this repo with `AI_VENTURE_OS_PROMPTS/`

Strategy, signal, portfolio, PnL and order concepts are now part of the
simulated paper layer only. Nothing sends an order to a real broker.
