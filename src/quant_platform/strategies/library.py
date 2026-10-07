"""Evidence-based allocation rules. Long-only, no leverage, no shorting.

References (academic evidence, not guarantees):

- Faber (2007), "A Quantitative Approach to Tactical Asset Allocation":
  10-month SMA trend filter per asset class.
- Antonacci (2014), "Dual Momentum Investing": relative + absolute
  12-month momentum between US and international equities with bonds as
  the defensive asset.
- Jegadeesh & Titman (1993) and Moskowitz, Ooi & Pedersen (2012):
  cross-sectional and time-series momentum.
- Inverse volatility / volatility targeting: Moreira & Muir (2017),
  "Volatility-Managed Portfolios".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from quant_platform.strategies.base import (
    StrategyContext,
    StrategyError,
    normalize_weights,
    trailing_return,
    trailing_volatility,
)

_MIN_LOOKBACK = 5


def _check_lookback(value: int, *, name: str) -> None:
    if value < _MIN_LOOKBACK:
        raise StrategyError(f"{name} must be >= {_MIN_LOOKBACK} sessions")


@dataclass(frozen=True, slots=True)
class BuyAndHold:
    """Benchmark: 100% in one symbol (default SPY)."""

    symbol: str = "SPY"
    name: str = "buy_and_hold"

    def params(self) -> dict[str, object]:
        return {"symbol": self.symbol}

    def warmup_days(self) -> int:
        return 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        weights = {self.symbol: 1.0} if self.symbol in context.symbols else {}
        return normalize_weights(weights, symbols=context.symbols, cash_symbol=None)


@dataclass(frozen=True, slots=True)
class SixtyForty:
    """Benchmark: 60% equities / 40% intermediate Treasuries."""

    equity_symbol: str = "SPY"
    bond_symbol: str = "IEF"
    equity_weight: float = 0.6
    name: str = "sixty_forty"

    def params(self) -> dict[str, object]:
        return {
            "equity_symbol": self.equity_symbol,
            "bond_symbol": self.bond_symbol,
            "equity_weight": self.equity_weight,
        }

    def warmup_days(self) -> int:
        return 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        weights: dict[str, float] = {}
        if self.equity_symbol in context.symbols:
            weights[self.equity_symbol] = self.equity_weight
        if self.bond_symbol in context.symbols:
            weights[self.bond_symbol] = 1.0 - self.equity_weight
        return normalize_weights(
            weights, symbols=context.symbols, cash_symbol=context.cash_symbol
        )


@dataclass(frozen=True, slots=True)
class TrendFollowing:
    """Faber-style trend filter: equal weight risk assets above their SMA."""

    lookback_days: int = 200
    name: str = "trend_following"

    def params(self) -> dict[str, object]:
        return {"lookback_days": self.lookback_days}

    def warmup_days(self) -> int:
        return self.lookback_days + 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        _check_lookback(self.lookback_days, name="lookback_days")
        assets = context.risk_symbols
        if not assets:
            raise StrategyError("trend_following needs risk assets in the universe")
        prices = context.prices[list(assets)]
        if len(prices.index) < self.lookback_days:
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        window = prices.iloc[-self.lookback_days :]
        complete = window.notna().sum() >= self.lookback_days
        sma = window.mean()
        last = prices.iloc[-1]
        above = [
            symbol
            for symbol in assets
            if bool(complete[symbol])
            and pd.notna(last[symbol])
            and float(last[symbol]) > float(sma[symbol])
        ]
        slot = 1.0 / len(assets)
        weights = dict.fromkeys(above, slot)
        return normalize_weights(
            weights, symbols=context.symbols, cash_symbol=context.cash_symbol
        )


@dataclass(frozen=True, slots=True)
class DualMomentum:
    """Antonacci GEM: best of US/international equity if it beats cash, else bonds."""

    lookback_days: int = 252
    equity_candidates: tuple[str, ...] = ("SPY", "EFA")
    defensive_symbol: str = "IEF"
    name: str = "dual_momentum"

    def params(self) -> dict[str, object]:
        return {
            "lookback_days": self.lookback_days,
            "equity_candidates": list(self.equity_candidates),
            "defensive_symbol": self.defensive_symbol,
        }

    def warmup_days(self) -> int:
        return self.lookback_days + 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        _check_lookback(self.lookback_days, name="lookback_days")
        candidates = context.available(self.equity_candidates)
        if not candidates:
            raise StrategyError("dual_momentum needs at least one equity candidate")
        momentum = trailing_return(context.prices, self.lookback_days)
        if momentum.empty or momentum[list(candidates)].isna().all():
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        best = str(momentum[list(candidates)].idxmax())
        hurdle = 0.0
        if context.cash_symbol is not None and context.cash_symbol in momentum.index:
            cash_momentum = momentum[context.cash_symbol]
            if pd.notna(cash_momentum):
                hurdle = float(cash_momentum)
        if float(momentum[best]) > hurdle:
            weights = {best: 1.0}
        elif self.defensive_symbol in context.symbols:
            weights = {self.defensive_symbol: 1.0}
        else:
            weights = {}
        return normalize_weights(
            weights, symbols=context.symbols, cash_symbol=context.cash_symbol
        )


@dataclass(frozen=True, slots=True)
class RelativeMomentumTopN:
    """Top-N risk assets by trailing return, only if they beat cash."""

    lookback_days: int = 126
    top_n: int = 3
    name: str = "relative_momentum_top_n"

    def params(self) -> dict[str, object]:
        return {"lookback_days": self.lookback_days, "top_n": self.top_n}

    def warmup_days(self) -> int:
        return self.lookback_days + 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        _check_lookback(self.lookback_days, name="lookback_days")
        if self.top_n < 1:
            raise StrategyError("top_n must be >= 1")
        assets = context.risk_symbols
        if not assets:
            raise StrategyError("relative_momentum needs risk assets in the universe")
        momentum = trailing_return(context.prices, self.lookback_days)
        if momentum.empty:
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        hurdle = 0.0
        if context.cash_symbol is not None and context.cash_symbol in momentum.index:
            cash_momentum = momentum[context.cash_symbol]
            if pd.notna(cash_momentum):
                hurdle = float(cash_momentum)
        ranked = momentum[list(assets)].dropna().sort_values(ascending=False)
        winners = [
            str(symbol)
            for symbol, value in ranked.head(self.top_n).items()
            if float(value) > hurdle
        ]
        slot = 1.0 / self.top_n
        weights = dict.fromkeys(winners, slot)
        return normalize_weights(
            weights, symbols=context.symbols, cash_symbol=context.cash_symbol
        )


@dataclass(frozen=True, slots=True)
class InverseVolatility:
    """Risk-parity-lite: weights ~ 1/vol, scaled to a volatility target.

    Gross exposure is capped at 1 (no leverage); any remainder goes to cash.
    """

    vol_lookback_days: int = 63
    target_volatility: float = 0.10
    name: str = "inverse_volatility"

    def params(self) -> dict[str, object]:
        return {
            "vol_lookback_days": self.vol_lookback_days,
            "target_volatility": self.target_volatility,
        }

    def warmup_days(self) -> int:
        return self.vol_lookback_days + 1

    def target_weights(self, context: StrategyContext) -> pd.Series:
        _check_lookback(self.vol_lookback_days, name="vol_lookback_days")
        if not 0.0 < self.target_volatility <= 1.0:
            raise StrategyError("target_volatility must be in (0, 1]")
        assets = tuple(
            symbol
            for symbol in context.risk_symbols + context.defensive_symbols
            if symbol != context.cash_symbol
        )
        if not assets:
            raise StrategyError("inverse_volatility needs non-cash assets")
        prices = context.prices[list(assets)]
        if len(prices.index) <= self.vol_lookback_days:
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        window = prices.iloc[-(self.vol_lookback_days + 1) :]
        complete = window.notna().all()
        prices = prices.loc[:, [str(c) for c in prices.columns if bool(complete[c])]]
        if prices.shape[1] == 0:
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        vol = trailing_volatility(prices, self.vol_lookback_days).dropna()
        vol = vol[vol > 0]
        if vol.empty:
            return normalize_weights(
                {}, symbols=context.symbols, cash_symbol=context.cash_symbol
            )
        inverse = 1.0 / vol
        base = inverse / inverse.sum()
        daily = prices.iloc[-(self.vol_lookback_days + 1) :].pct_change().dropna()
        daily = daily[list(base.index)]
        covariance = daily.cov(ddof=1).to_numpy(dtype="float64") * 252.0
        vector = base.to_numpy(dtype="float64")
        variance = float(vector @ covariance @ vector)
        portfolio_vol = math.sqrt(max(variance, 0.0))
        scale = (
            1.0
            if portfolio_vol <= 0
            else min(1.0, self.target_volatility / portfolio_vol)
        )
        weights = {str(symbol): float(value) * scale for symbol, value in base.items()}
        return normalize_weights(
            weights, symbols=context.symbols, cash_symbol=context.cash_symbol
        )
