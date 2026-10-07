"""Strategy rules: long-only, no leverage, no look-ahead. Synthetic prices."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant_platform.strategies import (
    BENCHMARK_STRATEGY_NAMES,
    STRATEGY_SPECS,
    StrategyContext,
    StrategyError,
    build_context,
    build_strategy,
    list_strategy_specs,
    normalize_weights,
    strategy_spec,
)

SYMBOLS = ("SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "GLD", "DBC", "BIL")


def _prices(days: int = 400, seed: int = 7) -> pd.DataFrame:
    """Deterministic geometric paths with different drifts per symbol."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-01", periods=days, tz="UTC")
    drifts = {
        "SPY": 0.0006,
        "QQQ": 0.0009,
        "IWM": 0.0002,
        "EFA": -0.0001,
        "EEM": -0.0004,
        "VNQ": 0.0001,
        "TLT": -0.0002,
        "IEF": 0.0001,
        "GLD": 0.0004,
        "DBC": -0.0006,
        "BIL": 0.00008,
    }
    vols = {
        "SPY": 0.012,
        "QQQ": 0.016,
        "IWM": 0.015,
        "EFA": 0.011,
        "EEM": 0.014,
        "VNQ": 0.013,
        "TLT": 0.009,
        "IEF": 0.004,
        "GLD": 0.008,
        "DBC": 0.012,
        "BIL": 0.0001,
    }
    data = {}
    for symbol in SYMBOLS:
        shocks = rng.normal(drifts[symbol], vols[symbol], size=days)
        data[symbol] = 100.0 * np.cumprod(1.0 + shocks)
    return pd.DataFrame(data, index=index)


def _assert_valid_weights(weights: pd.Series, context: StrategyContext) -> None:
    assert list(weights.index) == list(context.symbols)
    assert float(weights.min()) >= 0.0
    assert float(weights.sum()) <= 1.0 + 1e-9
    assert not weights.isna().any()


def test_registry_lists_specs_and_benchmarks() -> None:
    names = [spec.name for spec in list_strategy_specs()]
    assert names == [spec.name for spec in STRATEGY_SPECS]
    assert set(BENCHMARK_STRATEGY_NAMES) == {"buy_and_hold", "sixty_forty"}
    assert "trend_following" in names
    assert strategy_spec("dual_momentum").param_grid["lookback_days"]
    with pytest.raises(StrategyError):
        strategy_spec("nope")
    with pytest.raises(StrategyError):
        build_strategy("trend_following", {"unknown": 1})


def test_build_context_never_includes_future_rows() -> None:
    prices = _prices()
    as_of = prices.index[100]
    context = build_context(prices, as_of)
    assert context.prices.index[-1] == as_of
    assert context.cash_symbol == "BIL"
    assert "SPY" in context.risk_symbols
    assert "TLT" in context.defensive_symbols
    with pytest.raises(StrategyError):
        StrategyContext(
            prices=prices,
            as_of=as_of,
            risk_symbols=("SPY",),
            defensive_symbols=(),
            cash_symbol=None,
        )


def test_normalize_weights_caps_gross_and_parks_remainder_in_cash() -> None:
    weights = normalize_weights(
        {"SPY": 0.5, "QQQ": -0.2}, symbols=("SPY", "QQQ", "BIL"), cash_symbol="BIL"
    )
    assert weights["QQQ"] == 0.0
    assert math.isclose(weights["BIL"], 0.5)
    assert math.isclose(float(weights.sum()), 1.0)
    levered = normalize_weights(
        {"SPY": 2.0, "QQQ": 2.0}, symbols=("SPY", "QQQ", "BIL"), cash_symbol="BIL"
    )
    assert math.isclose(float(levered.sum()), 1.0)
    assert levered["BIL"] == 0.0


@pytest.mark.parametrize("name", [spec.name for spec in STRATEGY_SPECS])
def test_every_strategy_returns_valid_long_only_weights(name: str) -> None:
    prices = _prices()
    strategy = build_strategy(name)
    context = build_context(prices, prices.index[-1])
    weights = strategy.target_weights(context)
    _assert_valid_weights(weights, context)
    assert strategy.params()
    assert strategy.warmup_days() >= 1


@pytest.mark.parametrize("name", [spec.name for spec in STRATEGY_SPECS])
def test_no_look_ahead_future_rows_do_not_change_decision(name: str) -> None:
    prices = _prices(days=420)
    strategy = build_strategy(name)
    as_of = prices.index[300]
    truncated = build_context(prices.iloc[:301], as_of)
    with_future = build_context(prices, as_of)
    left = strategy.target_weights(truncated)
    right = strategy.target_weights(with_future)
    pd.testing.assert_series_equal(left, right)


def test_trend_following_goes_to_cash_when_everything_is_below_sma() -> None:
    index = pd.bdate_range("2021-01-01", periods=260, tz="UTC")
    falling = pd.DataFrame(
        {symbol: np.linspace(200.0, 100.0, 260) for symbol in SYMBOLS}, index=index
    )
    falling["BIL"] = 100.0
    strategy = build_strategy("trend_following", {"lookback_days": 200})
    weights = strategy.target_weights(build_context(falling))
    assert math.isclose(weights["BIL"], 1.0)
    rising = falling.iloc[::-1].set_axis(index)
    rising["BIL"] = 100.0
    weights_up = strategy.target_weights(build_context(rising))
    assert weights_up["BIL"] == 0.0
    assert math.isclose(float(weights_up.sum()), 1.0)


def test_dual_momentum_picks_best_equity_or_bonds() -> None:
    index = pd.bdate_range("2021-01-01", periods=300, tz="UTC")
    frame = pd.DataFrame(
        {
            "SPY": np.linspace(100, 130, 300),
            "EFA": np.linspace(100, 110, 300),
            "IEF": np.linspace(100, 101, 300),
            "BIL": np.linspace(100, 100.5, 300),
        },
        index=index,
    )
    strategy = build_strategy("dual_momentum", {"lookback_days": 252})
    weights = strategy.target_weights(build_context(frame))
    assert math.isclose(weights["SPY"], 1.0)
    bear = frame.copy()
    bear["SPY"] = np.linspace(130, 100, 300)
    bear["EFA"] = np.linspace(110, 100, 300)
    weights_bear = strategy.target_weights(build_context(bear))
    assert math.isclose(weights_bear["IEF"], 1.0)


def test_relative_momentum_top_n_respects_hurdle_and_count() -> None:
    prices = _prices()
    strategy = build_strategy(
        "relative_momentum_top_n", {"lookback_days": 126, "top_n": 2}
    )
    weights = strategy.target_weights(build_context(prices))
    invested = weights[weights > 0].drop(labels=["BIL"], errors="ignore")
    assert len(invested) <= 2
    assert all(math.isclose(value, 0.5) for value in invested)


def test_inverse_volatility_never_levers_and_tilts_to_low_vol() -> None:
    prices = _prices()
    strategy = build_strategy(
        "inverse_volatility", {"vol_lookback_days": 63, "target_volatility": 0.10}
    )
    weights = strategy.target_weights(build_context(prices))
    assert float(weights.sum()) <= 1.0 + 1e-9
    assert weights["IEF"] > weights["QQQ"]
    with pytest.raises(StrategyError):
        build_strategy("inverse_volatility", {"target_volatility": 2.0}).target_weights(
            build_context(prices)
        )


def test_warmup_returns_cash_only() -> None:
    prices = _prices(days=50)
    strategy = build_strategy("trend_following", {"lookback_days": 200})
    weights = strategy.target_weights(build_context(prices))
    assert math.isclose(weights["BIL"], 1.0)
