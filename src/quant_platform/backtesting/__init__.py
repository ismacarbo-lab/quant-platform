"""Vectorized strategy backtests with costs and walk-forward validation.

Distinct from :mod:`quant_platform.backtest`, which is the frozen research
dry-run engine (policies, no PnL). This package computes portfolio returns
for the paper-trading pivot (ADR 0005). Nothing here predicts the future.
"""

from quant_platform.backtesting.data import (
    PricePanel,
    load_price_panel,
    panel_from_frames,
)
from quant_platform.backtesting.engine import (
    BacktestConfig,
    BacktestResult,
    rebalance_mask,
    run_backtest,
)
from quant_platform.backtesting.metrics import PerformanceMetrics, compute_metrics
from quant_platform.backtesting.promotion import PromotionDecision, evaluate_promotion
from quant_platform.backtesting.walk_forward import (
    WalkForwardConfig,
    WalkForwardFold,
    WalkForwardResult,
    run_walk_forward,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "PerformanceMetrics",
    "PricePanel",
    "PromotionDecision",
    "WalkForwardConfig",
    "WalkForwardFold",
    "WalkForwardResult",
    "compute_metrics",
    "evaluate_promotion",
    "load_price_panel",
    "panel_from_frames",
    "rebalance_mask",
    "run_backtest",
    "run_walk_forward",
]
