"""Strategy catalog: specs, factories and parameter grids for walk-forward."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from quant_platform.strategies.base import Strategy, StrategyError, StrategySpec
from quant_platform.strategies.library import (
    BuyAndHold,
    DualMomentum,
    InverseVolatility,
    RelativeMomentumTopN,
    SixtyForty,
    TrendFollowing,
)

STRATEGY_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec(
        name="buy_and_hold",
        title="Buy & hold SPY",
        description="Benchmark: 100% S&P 500, no rebalancing decisions.",
        evidence="Market benchmark.",
        default_params={"symbol": "SPY"},
        is_benchmark=True,
    ),
    StrategySpec(
        name="sixty_forty",
        title="60/40 SPY/IEF",
        description="Benchmark: 60% equities, 40% intermediate Treasuries.",
        evidence="Classic balanced allocation benchmark.",
        default_params={
            "equity_symbol": "SPY",
            "bond_symbol": "IEF",
            "equity_weight": 0.6,
        },
        is_benchmark=True,
    ),
    StrategySpec(
        name="trend_following",
        title="Trend following (SMA filter)",
        description=(
            "Equal weight in risk assets trading above their moving average; "
            "the rest in T-bills."
        ),
        evidence="Faber (2007) 10-month SMA tactical asset allocation.",
        default_params={"lookback_days": 200},
        param_grid={"lookback_days": (126, 168, 200, 252)},
    ),
    StrategySpec(
        name="dual_momentum",
        title="Dual momentum (GEM)",
        description=(
            "Best of US vs international equities when it beats T-bills, "
            "otherwise intermediate Treasuries."
        ),
        evidence="Antonacci (2014) Global Equities Momentum.",
        default_params={
            "lookback_days": 252,
            "equity_candidates": ["SPY", "EFA"],
            "defensive_symbol": "IEF",
        },
        param_grid={"lookback_days": (126, 189, 252)},
    ),
    StrategySpec(
        name="relative_momentum_top_n",
        title="Relative momentum top-N",
        description=(
            "Top-N risk assets by trailing return if they beat T-bills; "
            "equal weight; rest in T-bills."
        ),
        evidence="Jegadeesh & Titman (1993); Moskowitz, Ooi & Pedersen (2012).",
        default_params={"lookback_days": 126, "top_n": 3},
        param_grid={"lookback_days": (63, 126, 252), "top_n": (2, 3, 4)},
    ),
    StrategySpec(
        name="inverse_volatility",
        title="Inverse volatility (vol target)",
        description=(
            "Weights proportional to 1/volatility across all assets, scaled to a "
            "volatility target; no leverage."
        ),
        evidence="Moreira & Muir (2017) volatility-managed portfolios.",
        default_params={"vol_lookback_days": 63, "target_volatility": 0.10},
        param_grid={
            "vol_lookback_days": (42, 63, 126),
            "target_volatility": (0.08, 0.10, 0.12),
        },
    ),
)

BENCHMARK_STRATEGY_NAMES: tuple[str, ...] = tuple(
    spec.name for spec in STRATEGY_SPECS if spec.is_benchmark
)

_FACTORIES: dict[str, Callable[..., Strategy]] = {
    "buy_and_hold": BuyAndHold,
    "sixty_forty": SixtyForty,
    "trend_following": TrendFollowing,
    "dual_momentum": DualMomentum,
    "relative_momentum_top_n": RelativeMomentumTopN,
    "inverse_volatility": InverseVolatility,
}


def list_strategy_specs() -> tuple[StrategySpec, ...]:
    return STRATEGY_SPECS


def strategy_spec(name: str) -> StrategySpec:
    for spec in STRATEGY_SPECS:
        if spec.name == name:
            return spec
    raise StrategyError(f"unknown strategy {name!r}")


def build_strategy(name: str, params: Mapping[str, object] | None = None) -> Strategy:
    """Instantiate a registered strategy with validated parameters."""
    spec = strategy_spec(name)
    factory = _FACTORIES[name]
    merged: dict[str, object] = dict(spec.default_params)
    merged.update(params or {})
    allowed = set(spec.default_params)
    unknown = sorted(set(merged) - allowed)
    if unknown:
        raise StrategyError(f"unknown parameters for {name}: {', '.join(unknown)}")
    kwargs = _coerce(name, merged)
    try:
        return factory(**kwargs)
    except TypeError as exc:
        raise StrategyError(f"invalid parameters for {name}") from exc


def _coerce(name: str, params: Mapping[str, object]) -> dict[str, object]:
    coerced: dict[str, object] = {}
    for key, value in params.items():
        if key == "equity_candidates" and isinstance(value, list | tuple):
            coerced[key] = tuple(str(item) for item in value)
        elif key in {"lookback_days", "top_n", "vol_lookback_days"}:
            coerced[key] = int(value)  # type: ignore[call-overload]
        elif key in {"target_volatility", "equity_weight"}:
            coerced[key] = float(value)  # type: ignore[arg-type]
        else:
            coerced[key] = str(value)
    return coerced
