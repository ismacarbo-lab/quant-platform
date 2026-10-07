"""Backtest engine, metrics, walk-forward and promotion on synthetic panels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from quant_platform.backtesting import (
    BacktestConfig,
    PricePanel,
    WalkForwardConfig,
    compute_metrics,
    evaluate_promotion,
    panel_from_frames,
    rebalance_mask,
    run_backtest,
    run_walk_forward,
)
from quant_platform.backtesting.data import total_return_factors
from quant_platform.backtesting.engine import BacktestError
from quant_platform.backtesting.metrics import monthly_returns, relative_metrics
from quant_platform.backtesting.runner import run_strategy_backtest_on_panel
from quant_platform.backtesting.walk_forward import WalkForwardError, oos_blocks
from quant_platform.marketdata.universe import DEFAULT_UNIVERSE
from quant_platform.research.normalization import (
    AdjustmentMode,
    assemble_normalized_dataset,
    build_normalization_request,
)
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
)
from quant_platform.strategies import build_strategy, strategy_spec
from quant_platform.strategies.base import StrategyContext

SYMBOLS = tuple(item.symbol for item in DEFAULT_UNIVERSE)


def _panel(days: int = 1600, seed: int = 11) -> PricePanel:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2015-01-01", periods=days, tz="UTC")
    data = {}
    for i, symbol in enumerate(SYMBOLS):
        drift = 0.0004 - 0.00005 * i
        vol = 0.001 if symbol == "BIL" else 0.008 + 0.001 * i
        if symbol == "BIL":
            drift = 0.00005
        data[symbol] = 100.0 * np.cumprod(1.0 + rng.normal(drift, vol, size=days))
    return panel_from_frames(pd.DataFrame(data, index=index))


@dataclass(frozen=True)
class _ConstantStrategy:
    weights: dict[str, float]
    name: str = "constant"

    def params(self) -> dict[str, object]:
        return {"weights": dict(self.weights)}

    def warmup_days(self) -> int:
        return 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        return pd.Series(self.weights).reindex(list(context.symbols)).fillna(0.0)


def test_rebalance_mask_marks_period_ends() -> None:
    index = pd.bdate_range("2024-01-01", periods=45, tz="UTC")
    monthly = rebalance_mask(index, "monthly")
    assert monthly.sum() == 3
    assert monthly.iloc[-1]
    assert str(index[monthly].to_list()[0].date()) == "2024-01-31"
    weekly = rebalance_mask(index, "weekly")
    assert weekly.sum() >= 9
    assert rebalance_mask(index, "daily").all()
    with pytest.raises(BacktestError):
        rebalance_mask(index, "yearly")


def test_buy_and_hold_tracks_asset_after_lag_and_cost() -> None:
    index = pd.bdate_range("2024-01-01", periods=6, tz="UTC")
    closes = pd.DataFrame(
        {"SPY": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0], "BIL": [1.0] * 6},
        index=index,
    )
    panel = panel_from_frames(closes)
    config = BacktestConfig(
        rebalance="daily", commission_bps=0.0, slippage_bps=10.0, initial_cash=1000.0
    )
    result = run_backtest(panel, _ConstantStrategy({"SPY": 1.0}), config)
    # Day 0 decision -> executed day 1 (cost 10 bps on 100% turnover).
    assert math.isclose(result.equity.iloc[1], 1000.0 * (1 - 0.001))
    # From day 2 on, equity follows SPY.
    expected_day2 = 1000.0 * (1 - 0.001) * (102.0 / 101.0)
    assert math.isclose(result.equity.iloc[2], expected_day2, rel_tol=1e-12)
    assert math.isclose(result.weights.iloc[-1]["SPY"], 1.0)
    assert result.turnover.iloc[1] == pytest.approx(1.0)
    assert result.turnover.iloc[2:].sum() == pytest.approx(0.0)
    assert result.rebalance_count == 5
    assert result.metrics.sessions == 6


def test_costs_reduce_equity_and_no_leverage_is_possible() -> None:
    panel = _panel(days=300)
    free = BacktestConfig(commission_bps=0.0, slippage_bps=0.0)
    costly = BacktestConfig(commission_bps=5.0, slippage_bps=10.0)
    strategy = build_strategy(
        "relative_momentum_top_n", {"lookback_days": 20, "top_n": 2}
    )
    cheap = run_backtest(panel, strategy, free)
    expensive = run_backtest(panel, strategy, costly)
    assert expensive.equity.iloc[-1] < cheap.equity.iloc[-1]
    assert expensive.metrics.total_costs > 0
    assert float(expensive.weights.sum(axis=1).max()) <= 1.0 + 1e-9
    assert float(expensive.weights.min().min()) >= -1e-12
    levered = run_backtest(panel, _ConstantStrategy({"SPY": 3.0, "QQQ": 3.0}), free)
    assert float(levered.weights.sum(axis=1).max()) <= 1.0 + 1e-9


def test_metrics_known_series() -> None:
    index = pd.bdate_range("2024-01-01", periods=4, tz="UTC")
    returns = pd.Series([0.1, -0.5, 0.2, 0.0], index=index)
    metrics = compute_metrics(returns, initial_equity=100.0)
    assert math.isclose(metrics.total_return, 1.1 * 0.5 * 1.2 - 1.0)
    assert math.isclose(metrics.max_drawdown, -0.5)
    assert metrics.worst_day == -0.5
    assert metrics.best_day == 0.2
    assert math.isclose(metrics.final_equity, 100.0 * 1.1 * 0.5 * 1.2)
    assert metrics.sharpe is not None and metrics.sharpe < 0
    payload = metrics.as_mapping()
    assert payload["start"] == "2024-01-01"
    assert payload["sessions"] == 4
    empty = compute_metrics(pd.Series(dtype="float64"))
    assert empty.sessions == 0
    assert empty.as_mapping()["cagr"] is None


def test_monthly_returns_compound_within_month() -> None:
    index = pd.DatetimeIndex(["2024-01-30", "2024-01-31", "2024-02-01"], tz="UTC")
    monthly = monthly_returns(pd.Series([0.1, 0.1, -0.1], index=index))
    assert math.isclose(monthly["2024-01"], 1.21 - 1.0)
    assert math.isclose(monthly["2024-02"], -0.1)
    rel = relative_metrics(
        pd.Series(
            [0.01, 0.02, -0.01, 0.0],
            index=pd.bdate_range("2024-01-01", periods=4, tz="UTC"),
        ),
        pd.Series(
            [0.01, 0.02, -0.01, 0.0],
            index=pd.bdate_range("2024-01-01", periods=4, tz="UTC"),
        ),
    )
    assert rel["beta"] == pytest.approx(1.0)
    assert rel["correlation"] == pytest.approx(1.0)


def test_total_return_factors_match_normalization_mode() -> None:
    index = pd.DatetimeIndex(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], tz="UTC"
    )
    closes = pd.DataFrame({"FICT": [100.0, 102.0, 101.0, 103.0]}, index=index)
    ex_time = pd.Timestamp("2024-01-04 13:30", tz="UTC")
    factors = total_return_factors(closes, {"FICT": [(ex_time, 2.04)]})
    assert factors["FICT"].to_list() == pytest.approx([0.98, 0.98, 1.0, 1.0])
    instrument = UUID("11111111-1111-1111-1111-111111111111")
    bars = tuple(
        DailyBarDatasetRow(
            instrument_id=instrument,
            symbol="FICT",
            exchange_code=None,
            asset_class="etf",
            currency="USD",
            observation_time=datetime(2024, 1, day, 21, tzinfo=UTC),
            available_time=datetime(2024, 1, day, 22, tzinfo=UTC),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=None,
            source_name="yfinance",
            ingestion_run_id=UUID("22222222-2222-2222-2222-222222222222"),
            is_correction=False,
            correction_reason=None,
        )
        for day, close in ((2, 100), (3, 102), (4, 101), (5, 103))
    )
    action = CorporateActionDatasetRow(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        instrument_id=instrument,
        symbol="FICT",
        exchange_code=None,
        asset_class="etf",
        action_type="dividend",
        effective_time=datetime(2024, 1, 4, 13, 30, tzinfo=UTC),
        available_time=datetime(2024, 1, 4, 14, 30, tzinfo=UTC),
        quantity_before=None,
        quantity_after=None,
        cash_amount=Decimal("2.04"),
        currency="USD",
        old_value=None,
        new_value=None,
        note=None,
    )
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 10, tzinfo=UTC),
        source_name="yfinance",
        adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        symbols=("FICT",),
    )
    normalized = assemble_normalized_dataset(
        request=request,
        raw_dataset=DailyBarsDataset(request=request.dataset_request(), rows=bars),
        visible_actions=(action,),
    )
    normalized_factors = [float(row.price_factor) for row in normalized.rows]
    assert normalized_factors == pytest.approx(factors["FICT"].to_list())


def test_panel_from_frames_adjusts_prices_and_hashes() -> None:
    index = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"], tz="UTC")
    closes = pd.DataFrame({"A": [10.0, 10.0, 10.0]}, index=index)
    panel = panel_from_frames(
        closes, dividends={"A": [(pd.Timestamp("2024-01-04", tz="UTC"), 1.0)]}
    )
    assert panel.closes["A"].to_list() == pytest.approx([9.0, 9.0, 10.0])
    assert panel.raw_closes["A"].to_list() == [10.0, 10.0, 10.0]
    assert panel.data_hash.startswith("sha256:")
    assert panel.coverage()["A"]["sessions"] == 3


def test_oos_blocks_and_walk_forward_select_params() -> None:
    panel = _panel(days=1600)  # ~6.3 years
    index = pd.DatetimeIndex(panel.closes.index)
    blocks = oos_blocks(index, min_is_years=3, oos_years=1)
    assert blocks[0][0] == 2018
    with pytest.raises(WalkForwardError):
        oos_blocks(index, min_is_years=10, oos_years=1)
    spec = strategy_spec("trend_following")
    result = run_walk_forward(
        panel,
        spec,
        config=BacktestConfig(),
        wf_config=WalkForwardConfig(min_is_years=3, oos_years=1, max_grid_size=2),
    )
    assert len(result.folds) >= 3
    assert not result.oos_returns.empty
    assert result.oos_start is not None and result.oos_start >= "2018-01-01"
    for fold in result.folds:
        assert fold.chosen_params["lookback_days"] in spec.param_grid["lookback_days"]
        assert fold.candidates == 2
    assert "lookback_days" in result.param_stability
    payload = result.as_mapping()
    assert payload["fold_count"] == len(result.folds)


def test_promotion_rule() -> None:
    index = pd.bdate_range("2020-01-01", periods=600, tz="UTC")
    good = compute_metrics(pd.Series(np.full(600, 0.0008), index=index))
    bench = compute_metrics(pd.Series(np.tile([0.01, -0.009], 300), index=index))
    decision = evaluate_promotion(good, bench)
    assert decision.eligible is True
    assert decision.reasons == ()
    bad = compute_metrics(pd.Series(np.tile([0.02, -0.025], 300), index=index))
    rejected = evaluate_promotion(bad, bench)
    assert rejected.eligible is False
    assert "oos_cagr_not_positive" in rejected.reasons
    short = compute_metrics(pd.Series(np.full(50, 0.001), index=index[:50]))
    assert "oos_too_short:50<252" in evaluate_promotion(short, bench).reasons


def test_runner_without_session_returns_outcome_and_hash() -> None:
    panel = _panel(days=1300)
    outcome = run_strategy_backtest_on_panel(
        None,
        panel,
        strategy_name="dual_momentum",
        params={"lookback_days": 126},
        config=BacktestConfig(),
        walk_forward=True,
        wf_config=WalkForwardConfig(min_is_years=3, oos_years=1, max_grid_size=3),
    )
    assert outcome.record_id is None
    assert outcome.result_hash.startswith("sha256:")
    assert outcome.benchmark.strategy_name == "buy_and_hold"
    assert outcome.walk_forward is not None
    assert outcome.promotion is not None
    summary = outcome.summary()
    assert summary["strategy_name"] == "dual_momentum"
    assert summary["params"] == {
        "lookback_days": 126,
        "equity_candidates": ["SPY", "EFA"],
        "defensive_symbol": "IEF",
    }
    benchmark_only = run_strategy_backtest_on_panel(
        None, panel, strategy_name="buy_and_hold", walk_forward=True
    )
    assert benchmark_only.walk_forward is None
