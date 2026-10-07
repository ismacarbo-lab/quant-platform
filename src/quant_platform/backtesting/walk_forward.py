"""Anchored walk-forward validation: pick params in-sample, judge out-of-sample.

For each out-of-sample block (one calendar year by default) the parameter
grid is evaluated on all data strictly before the block; the best in-sample
Sharpe is then run through the block. Stitching the blocks gives an
out-of-sample return series that never used its own data for selection.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from quant_platform.backtesting.data import PricePanel
from quant_platform.backtesting.engine import BacktestConfig, run_backtest
from quant_platform.backtesting.metrics import PerformanceMetrics, compute_metrics
from quant_platform.strategies.base import StrategySpec
from quant_platform.strategies.registry import build_strategy


class WalkForwardError(ValueError):
    """Raised when the panel is too short for the requested folds."""


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    min_is_years: int = 5
    oos_years: int = 1
    selection_metric: str = "sharpe"
    max_grid_size: int = 64

    def as_mapping(self) -> dict[str, object]:
        return {
            "min_is_years": self.min_is_years,
            "oos_years": self.oos_years,
            "selection_metric": self.selection_metric,
            "max_grid_size": self.max_grid_size,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    chosen_params: dict[str, object]
    is_metric: float | None
    oos_metrics: PerformanceMetrics
    candidates: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "is_start": self.is_start,
            "is_end": self.is_end,
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "chosen_params": dict(self.chosen_params),
            "is_metric": self.is_metric,
            "oos_metrics": self.oos_metrics.as_mapping(),
            "candidates": self.candidates,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    strategy_name: str
    config: WalkForwardConfig
    folds: tuple[WalkForwardFold, ...]
    oos_returns: pd.Series
    oos_metrics: PerformanceMetrics
    default_oos_metrics: PerformanceMetrics
    param_stability: dict[str, object] = field(default_factory=dict)

    @property
    def oos_start(self) -> str | None:
        return None if self.oos_returns.empty else str(self.oos_returns.index[0].date())

    @property
    def oos_end(self) -> str | None:
        return (
            None if self.oos_returns.empty else str(self.oos_returns.index[-1].date())
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "strategy_name": self.strategy_name,
            "config": self.config.as_mapping(),
            "fold_count": len(self.folds),
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "oos_metrics": self.oos_metrics.as_mapping(),
            "default_params_oos_metrics": self.default_oos_metrics.as_mapping(),
            "param_stability": dict(self.param_stability),
            "folds": [fold.as_mapping() for fold in self.folds],
        }


def parameter_grid(spec: StrategySpec, *, limit: int) -> list[dict[str, object]]:
    """Cartesian product of the spec grid merged over default params."""
    if not spec.param_grid:
        return [dict(spec.default_params)]
    keys = list(spec.param_grid)
    combos: list[dict[str, object]] = []
    for values in itertools.product(*(spec.param_grid[key] for key in keys)):
        params = dict(spec.default_params)
        params.update(dict(zip(keys, values, strict=True)))
        combos.append(params)
        if len(combos) >= limit:
            break
    return combos


def oos_blocks(
    index: pd.DatetimeIndex, *, min_is_years: int, oos_years: int
) -> list[tuple[int, int]]:
    """Return (first_oos_year, last_oos_year) pairs covering the panel."""
    years = sorted({int(year) for year in index.year})
    if len(years) < min_is_years + oos_years:
        raise WalkForwardError(
            f"need at least {min_is_years + oos_years} calendar years; got {len(years)}"
        )
    blocks: list[tuple[int, int]] = []
    cursor = years[0] + min_is_years
    while cursor <= years[-1]:
        blocks.append((cursor, min(cursor + oos_years - 1, years[-1])))
        cursor += oos_years
    return blocks


def run_walk_forward(
    panel: PricePanel,
    spec: StrategySpec,
    *,
    config: BacktestConfig | None = None,
    wf_config: WalkForwardConfig | None = None,
    symbols: Sequence[str] | None = None,
) -> WalkForwardResult:
    cfg = config or BacktestConfig()
    wf = wf_config or WalkForwardConfig()
    closes = panel.closes if symbols is None else panel.closes[list(symbols)]
    index = pd.DatetimeIndex(closes.dropna(how="all").index)
    blocks = oos_blocks(index, min_is_years=wf.min_is_years, oos_years=wf.oos_years)
    grid = parameter_grid(spec, limit=wf.max_grid_size)
    folds: list[WalkForwardFold] = []
    oos_pieces: list[pd.Series] = []
    default_pieces: list[pd.Series] = []
    chosen_history: list[dict[str, object]] = []

    for first_year, last_year in blocks:
        is_end = pd.Timestamp(f"{first_year}-01-01", tz="UTC") - pd.Timedelta(days=1)
        oos_end = pd.Timestamp(f"{last_year}-12-31", tz="UTC")
        is_index = index[index <= is_end]
        if is_index.empty:
            continue
        best_params: dict[str, object] | None = None
        best_metric: float | None = None
        for params in grid:
            strategy = build_strategy(spec.name, params)
            result = run_backtest(panel, strategy, cfg, end=is_end, symbols=symbols)
            metric = _selection_value(result.metrics, wf.selection_metric)
            if metric is None:
                continue
            if best_metric is None or metric > best_metric:
                best_metric = metric
                best_params = params
        if best_params is None:
            best_params = dict(spec.default_params)
        chosen = build_strategy(spec.name, best_params)
        full = run_backtest(panel, chosen, cfg, end=oos_end, symbols=symbols)
        oos_slice = full.returns.loc[full.returns.index > is_end]
        default_strategy = build_strategy(spec.name, dict(spec.default_params))
        default_full = run_backtest(
            panel, default_strategy, cfg, end=oos_end, symbols=symbols
        )
        default_slice = default_full.returns.loc[default_full.returns.index > is_end]
        oos_pieces.append(oos_slice)
        default_pieces.append(default_slice)
        chosen_history.append(dict(best_params))
        folds.append(
            WalkForwardFold(
                is_start=str(is_index[0].date()),
                is_end=str(is_end.date()),
                oos_start=str(oos_slice.index[0].date()) if not oos_slice.empty else "",
                oos_end=str(oos_slice.index[-1].date()) if not oos_slice.empty else "",
                chosen_params=dict(best_params),
                is_metric=best_metric,
                oos_metrics=compute_metrics(oos_slice),
                candidates=len(grid),
            )
        )
    oos_returns = pd.concat(oos_pieces) if oos_pieces else pd.Series(dtype="float64")
    default_returns = (
        pd.concat(default_pieces) if default_pieces else pd.Series(dtype="float64")
    )
    return WalkForwardResult(
        strategy_name=spec.name,
        config=wf,
        folds=tuple(folds),
        oos_returns=oos_returns,
        oos_metrics=compute_metrics(oos_returns),
        default_oos_metrics=compute_metrics(default_returns),
        param_stability=_stability(chosen_history),
    )


def _selection_value(metrics: PerformanceMetrics, name: str) -> float | None:
    value = metrics.as_mapping().get(name)
    if isinstance(value, int | float):
        return float(value)
    return None


def _stability(history: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not history:
        return {}
    summary: dict[str, object] = {}
    keys = sorted({key for params in history for key in params})
    for key in keys:
        values = [str(params.get(key)) for params in history]
        distinct = sorted(set(values))
        most_common = max(distinct, key=values.count)
        summary[key] = {
            "distinct_values": distinct,
            "most_common": most_common,
            "most_common_share": round(values.count(most_common) / len(values), 4),
        }
    return summary
