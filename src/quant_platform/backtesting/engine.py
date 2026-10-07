"""Daily portfolio simulation with costs and an execution lag.

Timeline for a rebalance decided at the close of session ``t``:

1. The strategy sees prices ``<= t`` only (``build_context``).
2. Orders execute at the close of ``t + execution_lag_days`` (default 1).
   Turnover pays ``commission_bps + slippage_bps`` basis points.
3. The new weights earn returns from the following session onward.

Between rebalances weights drift with prices. Uninvested cash earns 0;
strategies park cash in the cash symbol (BIL) explicitly when they want
a yield.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant_platform.backtesting.data import PricePanel
from quant_platform.backtesting.metrics import (
    PerformanceMetrics,
    compute_metrics,
    drawdown_series,
    monthly_table,
)
from quant_platform.marketdata.universe import (
    CASH_SYMBOL,
    DEFAULT_UNIVERSE,
    UniverseInstrument,
)
from quant_platform.strategies.base import Strategy, build_context

REBALANCE_FREQUENCIES: tuple[str, ...] = ("daily", "weekly", "monthly", "quarterly")


class BacktestError(ValueError):
    """Raised for invalid backtest configuration."""


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    rebalance: str = "monthly"
    commission_bps: float = 1.0
    slippage_bps: float = 5.0
    initial_cash: float = 100_000.0
    execution_lag_days: int = 1
    cash_symbol: str | None = CASH_SYMBOL
    universe: tuple[UniverseInstrument, ...] = field(default=DEFAULT_UNIVERSE)

    def __post_init__(self) -> None:
        if self.rebalance not in REBALANCE_FREQUENCIES:
            raise BacktestError(f"rebalance must be one of {REBALANCE_FREQUENCIES}")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise BacktestError("costs must be non-negative")
        if self.initial_cash <= 0:
            raise BacktestError("initial_cash must be positive")
        if self.execution_lag_days < 0:
            raise BacktestError("execution_lag_days must be >= 0")

    @property
    def cost_rate(self) -> float:
        return (self.commission_bps + self.slippage_bps) / 10_000.0

    def as_mapping(self) -> dict[str, object]:
        return {
            "rebalance": self.rebalance,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "initial_cash": self.initial_cash,
            "execution_lag_days": self.execution_lag_days,
            "cash_symbol": self.cash_symbol,
        }


@dataclass(frozen=True, slots=True)
class BacktestResult:
    strategy_name: str
    params: dict[str, object]
    config: BacktestConfig
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    targets: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    metrics: PerformanceMetrics
    rebalance_count: int
    first_invested: pd.Timestamp | None

    @property
    def exposure(self) -> pd.Series:
        result: pd.Series = self.weights.sum(axis=1)
        return result

    def drawdowns(self) -> pd.Series:
        return drawdown_series(self.returns)

    def latest_weights(self) -> dict[str, float]:
        if self.weights.empty:
            return {}
        last = self.weights.iloc[-1]
        return {str(k): round(float(v), 6) for k, v in last.items() if float(v) > 1e-9}

    def equity_points(
        self, *, max_points: int | None = None
    ) -> list[dict[str, object]]:
        series = self.equity
        if max_points is not None and len(series) > max_points:
            step = max(1, len(series) // max_points)
            positions = np.array(
                sorted({*range(0, len(series), step), len(series) - 1}), dtype="int64"
            )
            series = series.iloc[positions]
        return [
            {
                "date": str(pd.Timestamp(str(stamp)).date()),
                "equity": round(float(value), 4),
            }
            for stamp, value in series.items()
        ]

    def monthly(self) -> list[dict[str, object]]:
        return monthly_table(self.returns)


def rebalance_mask(index: pd.DatetimeIndex, frequency: str) -> pd.Series:
    """True on the last session of each period (or every day)."""
    if frequency == "daily":
        return pd.Series(True, index=index)
    naive = index.tz_convert(None) if index.tz is not None else index
    if frequency == "weekly":
        keys = naive.to_period("W").astype(str)
    elif frequency == "monthly":
        keys = naive.to_period("M").astype(str)
    elif frequency == "quarterly":
        keys = naive.to_period("Q").astype(str)
    else:
        raise BacktestError(f"unknown rebalance frequency {frequency!r}")
    key_series = pd.Series(keys, index=index)
    last_of_period = key_series != key_series.shift(-1)
    return last_of_period.astype(bool)


def run_backtest(
    panel: PricePanel,
    strategy: Strategy,
    config: BacktestConfig | None = None,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    symbols: Sequence[str] | None = None,
) -> BacktestResult:
    """Simulate ``strategy`` on ``panel`` closes. Deterministic, no network."""
    cfg = config or BacktestConfig()
    closes = panel.closes if symbols is None else panel.closes[list(symbols)]
    if start is not None:
        closes = closes.loc[closes.index >= pd.Timestamp(start)]
    if end is not None:
        closes = closes.loc[closes.index <= pd.Timestamp(end)]
    closes = closes.dropna(how="all")
    if closes.shape[0] < 2:
        raise BacktestError("at least two sessions are required")
    index = pd.DatetimeIndex(closes.index)
    columns = [str(column) for column in closes.columns]
    n_days = len(index)
    n_assets = len(columns)
    price_matrix = closes.to_numpy(dtype="float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        daily_returns = price_matrix[1:] / price_matrix[:-1] - 1.0
    daily_returns = np.vstack([np.zeros((1, n_assets)), daily_returns])
    daily_returns = np.nan_to_num(daily_returns, nan=0.0, posinf=0.0, neginf=0.0)
    mask = rebalance_mask(index, cfg.rebalance).to_numpy()
    warmup = max(1, int(strategy.warmup_days()))

    held = np.zeros(n_assets, dtype="float64")
    equity_value = float(cfg.initial_cash)
    equity = np.empty(n_days, dtype="float64")
    port_returns = np.zeros(n_days, dtype="float64")
    weights_history = np.zeros((n_days, n_assets), dtype="float64")
    targets_history = np.full((n_days, n_assets), np.nan, dtype="float64")
    turnover = np.zeros(n_days, dtype="float64")
    costs = np.zeros(n_days, dtype="float64")
    pending: tuple[int, np.ndarray] | None = None
    rebalances = 0
    first_invested: pd.Timestamp | None = None

    for i in range(n_days):
        r = daily_returns[i]
        port_ret = float(held @ r)
        equity_value *= 1.0 + port_ret
        if 1.0 + port_ret != 0.0:
            held = held * (1.0 + r) / (1.0 + port_ret)
        port_returns[i] = port_ret
        if pending is not None and pending[0] == i:
            target = pending[1]
            delta = float(np.abs(target - held).sum())
            cost_fraction = delta * cfg.cost_rate
            equity_value *= 1.0 - cost_fraction
            turnover[i] = delta
            costs[i] = cost_fraction * equity_value / max(1.0 - cost_fraction, 1e-12)
            port_returns[i] = (1.0 + port_returns[i]) * (1.0 - cost_fraction) - 1.0
            held = target.copy()
            pending = None
            if first_invested is None and float(held.sum()) > 0:
                first_invested = pd.Timestamp(index[i])
        if mask[i] and i + 1 >= warmup:
            context = build_context(
                closes.iloc[: i + 1],
                index[i],
                universe=cfg.universe,
                cash_symbol=cfg.cash_symbol,
            )
            weights = strategy.target_weights(context)
            target = (
                weights.reindex(columns)
                .fillna(0.0)
                .clip(lower=0.0)
                .to_numpy(dtype="float64")
            )
            gross = float(target.sum())
            if gross > 1.0:
                target = target / gross
            targets_history[i] = target
            exec_index = i + cfg.execution_lag_days
            if exec_index < n_days:
                pending = (exec_index, target)
                rebalances += 1
        equity[i] = equity_value
        weights_history[i] = held

    equity_series = pd.Series(equity, index=index, name="equity")
    returns_series = pd.Series(port_returns, index=index, name="returns")
    weights_frame = pd.DataFrame(weights_history, index=index, columns=columns)
    targets_frame = pd.DataFrame(targets_history, index=index, columns=columns)
    turnover_series = pd.Series(turnover, index=index, name="turnover")
    costs_series = pd.Series(costs, index=index, name="costs")
    metrics = compute_metrics(
        returns_series,
        turnover=turnover_series,
        costs=costs_series,
        exposure=weights_frame.sum(axis=1),
        initial_equity=cfg.initial_cash,
    )
    return BacktestResult(
        strategy_name=strategy.name,
        params=dict(strategy.params()),
        config=cfg,
        equity=equity_series,
        returns=returns_series,
        weights=weights_frame,
        targets=targets_frame,
        turnover=turnover_series,
        costs=costs_series,
        metrics=metrics,
        rebalance_count=rebalances,
        first_invested=first_invested,
    )
