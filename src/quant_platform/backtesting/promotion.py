"""Promotion rule: which strategies may run in paper trading.

Out-of-sample only. A strategy is eligible when its walk-forward OOS
Sharpe beats the benchmark's over the same window, its OOS max drawdown is
not worse than the benchmark's, and its OOS CAGR is positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_platform.backtesting.metrics import PerformanceMetrics


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    eligible: bool
    reasons: tuple[str, ...]
    strategy_sharpe: float | None
    benchmark_sharpe: float | None
    strategy_max_drawdown: float | None
    benchmark_max_drawdown: float | None
    strategy_cagr: float | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "strategy_sharpe": self.strategy_sharpe,
            "benchmark_sharpe": self.benchmark_sharpe,
            "strategy_max_drawdown": self.strategy_max_drawdown,
            "benchmark_max_drawdown": self.benchmark_max_drawdown,
            "strategy_cagr": self.strategy_cagr,
        }


def evaluate_promotion(
    strategy: PerformanceMetrics,
    benchmark: PerformanceMetrics,
    *,
    min_sessions: int = 252,
) -> PromotionDecision:
    reasons: list[str] = []
    s = strategy.as_mapping()
    b = benchmark.as_mapping()
    s_sharpe = _num(s["sharpe"])
    b_sharpe = _num(b["sharpe"])
    s_dd = _num(s["max_drawdown"])
    b_dd = _num(b["max_drawdown"])
    s_cagr = _num(s["cagr"])
    if strategy.sessions < min_sessions:
        reasons.append(f"oos_too_short:{strategy.sessions}<{min_sessions}")
    if s_sharpe is None or b_sharpe is None:
        reasons.append("sharpe_unavailable")
    elif s_sharpe <= b_sharpe:
        reasons.append("oos_sharpe_not_above_benchmark")
    if s_dd is None or b_dd is None:
        reasons.append("drawdown_unavailable")
    elif s_dd < b_dd:
        reasons.append("oos_drawdown_worse_than_benchmark")
    if s_cagr is None or s_cagr <= 0:
        reasons.append("oos_cagr_not_positive")
    return PromotionDecision(
        eligible=not reasons,
        reasons=tuple(reasons),
        strategy_sharpe=s_sharpe,
        benchmark_sharpe=b_sharpe,
        strategy_max_drawdown=s_dd,
        benchmark_max_drawdown=b_dd,
        strategy_cagr=s_cagr,
    )


def _num(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
