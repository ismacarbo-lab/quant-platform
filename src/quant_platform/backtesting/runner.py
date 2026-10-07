"""Run a strategy against the stored panel, compare to the benchmark, persist."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform import __version__
from quant_platform.backtesting.data import PricePanel, load_price_panel
from quant_platform.backtesting.engine import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from quant_platform.backtesting.metrics import relative_metrics
from quant_platform.backtesting.models import StrategyBacktestRecord
from quant_platform.backtesting.promotion import PromotionDecision, evaluate_promotion
from quant_platform.backtesting.walk_forward import (
    WalkForwardConfig,
    WalkForwardError,
    WalkForwardResult,
    run_walk_forward,
)
from quant_platform.marketdata.universe import (
    DEFAULT_UNIVERSE,
    UniverseInstrument,
    universe_symbols,
)
from quant_platform.strategies.registry import build_strategy, strategy_spec

DEFAULT_BENCHMARK = "buy_and_hold"
EQUITY_CURVE_MAX_POINTS = 2600


@dataclass(frozen=True, slots=True)
class StrategyBacktestOutcome:
    record_id: UUID | None
    strategy_name: str
    params: dict[str, object]
    result: BacktestResult
    benchmark: BacktestResult
    relative: dict[str, float | None]
    walk_forward: WalkForwardResult | None
    promotion: PromotionDecision | None
    result_hash: str
    data_hash: str

    def summary(self) -> dict[str, object]:
        return {
            "record_id": None if self.record_id is None else str(self.record_id),
            "strategy_name": self.strategy_name,
            "params": dict(self.params),
            "metrics": self.result.metrics.as_mapping(),
            "benchmark_name": self.benchmark.strategy_name,
            "benchmark_metrics": self.benchmark.metrics.as_mapping(),
            "relative_metrics": dict(self.relative),
            "walk_forward": None
            if self.walk_forward is None
            else self.walk_forward.as_mapping(),
            "promotion": None
            if self.promotion is None
            else self.promotion.as_mapping(),
            "result_hash": self.result_hash,
            "data_hash": self.data_hash,
        }


def run_strategy_backtest(
    session: Session,
    *,
    strategy_name: str,
    params: Mapping[str, object] | None = None,
    source_name: str,
    start: date,
    end: date,
    as_of: datetime | None = None,
    config: BacktestConfig | None = None,
    universe: Sequence[UniverseInstrument] = DEFAULT_UNIVERSE,
    benchmark_name: str = DEFAULT_BENCHMARK,
    walk_forward: bool = True,
    wf_config: WalkForwardConfig | None = None,
    store: bool = True,
    git_commit: str | None = None,
    panel: PricePanel | None = None,
) -> StrategyBacktestOutcome:
    """Load the PIT panel, run strategy + benchmark (+ walk-forward), persist."""
    cfg = config or BacktestConfig(universe=tuple(universe))
    stamp = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    symbols = universe_symbols(universe)
    data = panel or load_price_panel(
        session,
        source_name=source_name,
        symbols=symbols,
        start=start,
        end=end,
        as_of=stamp,
    )
    return run_strategy_backtest_on_panel(
        session if store else None,
        data,
        strategy_name=strategy_name,
        params=params,
        config=cfg,
        benchmark_name=benchmark_name,
        walk_forward=walk_forward,
        wf_config=wf_config,
        git_commit=git_commit,
    )


def run_strategy_backtest_on_panel(
    session: Session | None,
    panel: PricePanel,
    *,
    strategy_name: str,
    params: Mapping[str, object] | None = None,
    config: BacktestConfig | None = None,
    benchmark_name: str = DEFAULT_BENCHMARK,
    walk_forward: bool = True,
    wf_config: WalkForwardConfig | None = None,
    git_commit: str | None = None,
) -> StrategyBacktestOutcome:
    """Same as :func:`run_strategy_backtest` but with a prepared panel.

    Passing ``session=None`` skips persistence.
    """
    cfg = config or BacktestConfig()
    spec = strategy_spec(strategy_name)
    strategy = build_strategy(strategy_name, params)
    result = run_backtest(panel, strategy, cfg)
    benchmark_strategy = build_strategy(benchmark_name)
    benchmark = run_backtest(panel, benchmark_strategy, cfg)
    relative = relative_metrics(result.returns, benchmark.returns)
    wf_result: WalkForwardResult | None = None
    promotion: PromotionDecision | None = None
    if walk_forward and not spec.is_benchmark:
        try:
            wf_result = run_walk_forward(panel, spec, config=cfg, wf_config=wf_config)
        except WalkForwardError:
            wf_result = None
        if wf_result is not None and not wf_result.oos_returns.empty:
            bench_oos = benchmark.returns.loc[wf_result.oos_returns.index]
            from quant_platform.backtesting.metrics import compute_metrics

            promotion = evaluate_promotion(
                wf_result.oos_metrics, compute_metrics(bench_oos)
            )
    result_hash = _result_hash(result, benchmark, wf_result)
    record_id: UUID | None = None
    if session is not None:
        record = StrategyBacktestRecord(
            strategy_name=strategy_name,
            strategy_title=spec.title,
            params=dict(result.params),
            benchmark_name=benchmark_name,
            source_name=panel.source_name,
            symbols=list(panel.symbols),
            start_date=panel.start.date(),
            end_date=panel.end.date(),
            as_of=panel.as_of.to_pydatetime(),
            rebalance=cfg.rebalance,
            commission_bps=cfg.commission_bps,
            slippage_bps=cfg.slippage_bps,
            initial_cash=cfg.initial_cash,
            session_count=panel.session_count,
            rebalance_count=result.rebalance_count,
            metrics=result.metrics.as_mapping(),
            benchmark_metrics=benchmark.metrics.as_mapping(),
            relative_metrics=dict(relative),
            walk_forward=None if wf_result is None else wf_result.as_mapping(),
            promotion=None if promotion is None else promotion.as_mapping(),
            promotion_eligible=None if promotion is None else promotion.eligible,
            equity_curve=_merged_equity_curve(result, benchmark),
            monthly_returns=result.monthly(),
            latest_weights=result.latest_weights(),
            data_hash=panel.data_hash,
            result_hash=result_hash,
            package_version=__version__,
            git_commit=git_commit,
        )
        session.add(record)
        session.flush()
        record_id = record.id
    return StrategyBacktestOutcome(
        record_id=record_id,
        strategy_name=strategy_name,
        params=dict(result.params),
        result=result,
        benchmark=benchmark,
        relative=relative,
        walk_forward=wf_result,
        promotion=promotion,
        result_hash=result_hash,
        data_hash=panel.data_hash,
    )


def list_strategy_backtests(
    session: Session, *, limit: int = 50, strategy_name: str | None = None
) -> list[StrategyBacktestRecord]:
    stmt = select(StrategyBacktestRecord).order_by(
        StrategyBacktestRecord.created_at.desc()
    )
    if strategy_name is not None:
        stmt = stmt.where(StrategyBacktestRecord.strategy_name == strategy_name)
    return list(session.scalars(stmt.limit(limit)))


def get_strategy_backtest(
    session: Session, record_id: UUID
) -> StrategyBacktestRecord | None:
    return session.get(StrategyBacktestRecord, record_id)


def latest_backtest_per_strategy(session: Session) -> list[StrategyBacktestRecord]:
    """Most recent record for every strategy name (for the ranking view)."""
    rows = list_strategy_backtests(session, limit=500)
    latest: dict[str, StrategyBacktestRecord] = {}
    for row in rows:
        latest.setdefault(row.strategy_name, row)
    return sorted(latest.values(), key=lambda row: row.strategy_name)


def record_summary(record: StrategyBacktestRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "created_at": record.created_at.isoformat(),
        "strategy_name": record.strategy_name,
        "strategy_title": record.strategy_title,
        "params": dict(record.params),
        "benchmark_name": record.benchmark_name,
        "source_name": record.source_name,
        "symbols": list(record.symbols),
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
        "as_of": record.as_of.isoformat(),
        "rebalance": record.rebalance,
        "commission_bps": float(record.commission_bps),
        "slippage_bps": float(record.slippage_bps),
        "initial_cash": float(record.initial_cash),
        "session_count": record.session_count,
        "rebalance_count": record.rebalance_count,
        "metrics": dict(record.metrics),
        "benchmark_metrics": dict(record.benchmark_metrics),
        "relative_metrics": dict(record.relative_metrics),
        "promotion": None if record.promotion is None else dict(record.promotion),
        "promotion_eligible": record.promotion_eligible,
        "walk_forward_oos_metrics": (
            None
            if record.walk_forward is None
            else record.walk_forward.get("oos_metrics")
        ),
        "latest_weights": dict(record.latest_weights),
        "data_hash": record.data_hash,
        "result_hash": record.result_hash,
        "package_version": record.package_version,
    }


def record_detail(record: StrategyBacktestRecord) -> dict[str, object]:
    payload = record_summary(record)
    payload["walk_forward"] = record.walk_forward
    payload["equity_curve"] = list(record.equity_curve)
    payload["monthly_returns"] = list(record.monthly_returns)
    return payload


def _merged_equity_curve(
    result: BacktestResult, benchmark: BacktestResult
) -> list[dict[str, object]]:
    strategy_points = result.equity_points(max_points=EQUITY_CURVE_MAX_POINTS)
    bench = benchmark.equity
    merged: list[dict[str, object]] = []
    for point in strategy_points:
        stamp = pd.Timestamp(str(point["date"]), tz="UTC")
        bench_value = bench.get(stamp)
        merged.append(
            {
                "date": point["date"],
                "equity": point["equity"],
                "benchmark": None
                if bench_value is None
                else round(float(bench_value), 4),
            }
        )
    return merged


def _result_hash(
    result: BacktestResult,
    benchmark: BacktestResult,
    wf_result: WalkForwardResult | None,
) -> str:
    payload = {
        "strategy": result.strategy_name,
        "params": result.params,
        "config": result.config.as_mapping(),
        "metrics": result.metrics.as_mapping(),
        "benchmark": benchmark.strategy_name,
        "benchmark_metrics": benchmark.metrics.as_mapping(),
        "walk_forward": None
        if wf_result is None
        else wf_result.oos_metrics.as_mapping(),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
