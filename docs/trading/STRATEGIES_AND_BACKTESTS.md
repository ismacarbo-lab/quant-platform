# Strategies and backtests

Modules: `quant_platform.strategies`, `quant_platform.backtesting`.
Script: `scripts/run-strategy-backtest.py` (`make backtest-all`).
API: `GET /api/strategies`, `GET /api/backtests/ranking`,
`GET /api/backtests/{id}`, `POST /api/backtests/run`.

## Strategy interface

`Strategy.target_weights(context)` returns long-only weights (sum ≤ 1) from
a `StrategyContext` whose price frame ends at `as_of`. `build_context`
slices the panel, and `StrategyContext` refuses rows after `as_of`. Every
strategy has a unit test proving that appending future rows does not
change the decision at `as_of`.

| Name | Rule | Evidence |
|------|------|----------|
| `buy_and_hold` | 100% SPY | benchmark |
| `sixty_forty` | 60% SPY / 40% IEF | benchmark |
| `trend_following` | equal weight risk assets above their SMA(200); rest in BIL | Faber (2007) |
| `dual_momentum` | best of SPY/EFA by 12-month return if above BIL, else IEF | Antonacci (2014) |
| `relative_momentum_top_n` | top-3 risk assets by 6-month return above BIL; equal weight | Jegadeesh & Titman (1993); Moskowitz, Ooi & Pedersen (2012) |
| `inverse_volatility` | weights ∝ 1/vol, scaled to a 10% vol target, no leverage | Moreira & Muir (2017) |

## Backtest engine

- Daily loop over total-return adjusted closes. Weights drift with prices.
- Decision at the close of a rebalance session (monthly by default);
  execution one session later (`execution_lag_days = 1`); new weights earn
  from the following session.
- Turnover pays `commission_bps + slippage_bps` (1 + 5 bps by default).
- Uninvested cash earns 0; strategies park cash in BIL explicitly.
- Metrics: CAGR, annual volatility, Sharpe (rf = 0), Sortino, max
  drawdown, Calmar, best/worst day and month, positive months, annual
  turnover, total costs, average exposure.

## Walk-forward validation

Anchored folds with one calendar year out-of-sample each (first fold after
5 in-sample years). For each fold the parameter grid is scored by Sharpe
on data strictly before the block; the chosen parameters run through the
block. Stitched OOS returns give the OOS metrics shown in the dashboard,
next to the OOS metrics of the fixed default parameters and a parameter
stability summary.

## Promotion rule

A strategy is "apto para paper" only if its walk-forward OOS Sharpe beats
the benchmark's over the same window, its OOS max drawdown is not worse,
and its OOS CAGR is positive. On the 2005–2026 panel no tactical strategy
passed against buy-and-hold SPY: the 2010–2026 US bull market made SPY the
best risk-adjusted asset out of sample (SPY OOS Sharpe 0.87 vs 0.51–0.73).
The tactical strategies did cut drawdowns roughly in half. The paper
accounts run anyway so the comparison keeps being measured forward.

## Persistence

`strategy_backtests` (Alembic `0011`): config, metrics, benchmark
metrics, relative metrics, walk-forward JSON, promotion verdict,
downsampled equity curve, monthly returns, latest weights, data hash and
result hash. The dashboard ranking shows the latest record per strategy.
