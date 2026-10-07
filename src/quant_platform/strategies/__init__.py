"""Long-only allocation strategies over the ETF universe (ADR 0005).

A strategy maps the prices visible at ``as_of`` to target weights. It
never sees future bars: the engine hands it a ``StrategyContext`` whose
price frame ends at ``as_of``. Nothing here guarantees profits.
"""

from quant_platform.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyError,
    StrategySpec,
    build_context,
    normalize_weights,
)
from quant_platform.strategies.library import (
    BuyAndHold,
    DualMomentum,
    InverseVolatility,
    RelativeMomentumTopN,
    SixtyForty,
    TrendFollowing,
)
from quant_platform.strategies.registry import (
    BENCHMARK_STRATEGY_NAMES,
    STRATEGY_SPECS,
    build_strategy,
    list_strategy_specs,
    strategy_spec,
)

__all__ = [
    "BENCHMARK_STRATEGY_NAMES",
    "STRATEGY_SPECS",
    "BuyAndHold",
    "DualMomentum",
    "InverseVolatility",
    "RelativeMomentumTopN",
    "SixtyForty",
    "Strategy",
    "StrategyContext",
    "StrategyError",
    "StrategySpec",
    "TrendFollowing",
    "build_context",
    "build_strategy",
    "list_strategy_specs",
    "normalize_weights",
    "strategy_spec",
]
