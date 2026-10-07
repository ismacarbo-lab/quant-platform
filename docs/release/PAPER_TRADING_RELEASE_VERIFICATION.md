# Paper-trading pivot — release verification and tag proposal

Local verification of the ADR 0005 pivot: real market data, strategies,
backtests with costs and walk-forward, simulated paper trading with
fictional money, local dashboard. **No real money, no live trading, no
real broker, no credentials, no AI runtime.**

Related: [ADR 0005](../adr/0005-paper-trading-pivot.md),
[CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[RISK_REGISTER.md](RISK_REGISTER.md),
[MARKET_DATA.md](../trading/MARKET_DATA.md),
[STRATEGIES_AND_BACKTESTS.md](../trading/STRATEGIES_AND_BACKTESTS.md),
[PAPER_TRADING.md](../trading/PAPER_TRADING.md).

This report is a **tag proposal only**. The tag `v0.7.0-paper-trading`
was **not** created and **not** pushed.

## Verification (local, 2026-10-07)

| Check | Result |
|-------|--------|
| `make quality` | ruff clean, 371 files formatted, mypy 162 files, 515 fast tests, Compose config OK |
| `uv run pytest` (fast + PostgreSQL) | 681 passed |
| `make policy-regression` | 18/18, hash `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` (unchanged) |
| `make normalization-regression` | 6/6, hash `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` (unchanged) |
| `make data-contract-conformance-regression` | 5/5, hash `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` (unchanged) |
| `make data-contract-schema-compatibility` | compatible, 0 issues, hash `sha256:9028236e3a8017a9ed89f2549ff72a7a8e20c205e8ff8ecd56f393de728fabb2` (baseline regenerated: `source_kind` gained `vendor_api`) |
| `make contract-payload-intake-regression` | 5/5, hash `sha256:109d98a0434206ff9f73a67eab369c47b6dc6c7faddb932007d22c07bb8dc5ad` (unchanged) |
| `make research-release-check` | `ok=true`, `alembic=0012_paper_trading`, `trading_constructs=none`, `ai_runtime=none` |
| `make dashboard-typecheck` / `make dashboard-build` | TypeScript strict clean; Vite build OK |
| `uv run alembic current` | `0012_paper_trading (head)` |

## Real data loaded (local PostgreSQL)

`make fetch-data` from 2005-01-01: 63,737 daily bars and 1,092 dividends
for SPY, QQQ, IWM, EFA, EEM, VNQ, TLT, IEF, GLD, DBC, BIL and BTC-USD
(last session 2026-10-06). Zero sanitized bars, no errors. Dry-run against
Yahoo for SPY confirmed the `yfinance` 1.7 API path.

## Backtests (2005-01-03 → 2026-10-06, monthly rebalance, 1 + 5 bps)

| Strategy | CAGR | Vol | Sharpe | MaxDD | OOS Sharpe (2010–2026) | Promotion |
|----------|-----:|----:|-------:|------:|-----------------------:|-----------|
| inverse_volatility | 6.8% | 8.7% | 0.80 | -22.8% | 0.73 | no |
| sixty_forty (benchmark) | 8.2% | 10.6% | 0.79 | -32.2% | — | — |
| buy_and_hold SPY (benchmark) | 11.0% | 18.9% | 0.65 | -55.2% | — | — |
| trend_following | 6.7% | 11.1% | 0.64 | -21.5% | 0.58 | no |
| relative_momentum_top_n | 8.7% | 15.9% | 0.60 | -31.1% | 0.65 | no |
| dual_momentum | 7.3% | 15.8% | 0.53 | -33.7% | 0.51 | no |

SPY's OOS Sharpe over the same 2010–2026 window was 0.87, so no tactical
strategy passed the promotion rule (risk R24). They did cut the maximum
drawdown roughly in half. This is reported as-is; the rule was not
loosened.

## Paper trading

`make paper-replay FROM=2024-01-02` bootstrapped six accounts (100,000
fictional USD each) and replayed 693 sessions in about 90 seconds. Equity
on 2026-10-06: buy_and_hold 170,901; trend_following 140,969; sixty_forty
140,843; relative_momentum_top_n 136,000; inverse_volatility 134,172;
dual_momentum 133,640. Re-running the latest session is a no-op.

## Dashboard

Served by FastAPI at `http://127.0.0.1:8000` (`make app`). Verified in
the browser: overview, strategies (log equity curves, comparison,
catalog), backtest detail (equity vs benchmark, drawdown, weights,
monthly heatmap, walk-forward folds), paper account (equity vs SPY,
drawdown, allocation, positions, orders, fills, runs), market
candlesticks with adjusted close and volume, data coverage and jobs.

## Guardrails that remain

- `APP_MODE=live` rejected; `paper` required for any paper mutation.
- No broker SDKs (`alpaca`, `ccxt`, `ib_insync` … still forbidden
  dependencies); no credentials; no AI runtime.
- `yfinance` imported lazily in one module only; tests use recorded
  fixtures; CI has no network calls.
- Silver `daily_bars` never updated or deleted; restatements are new PIT
  rows.
- Research regression matrices unchanged.

## Proposed tag

**Not created. Not pushed.**

```bash
cd /home/isma/invest
git tag -a v0.7.0-paper-trading -m "Paper trading pivot: real data, strategies, backtests, dashboard"
git push origin v0.7.0-paper-trading
```

Rollback:

```bash
git tag -d v0.7.0-paper-trading
git push origin :refs/tags/v0.7.0-paper-trading
```

## Out of scope

Real money, live trading, real brokers, leverage, short selling,
intraday, options/futures, ML/AI as a trading brain, cloud storage.
