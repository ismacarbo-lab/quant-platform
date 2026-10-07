"""Strategy interface and the point-in-time context it receives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd

from quant_platform.marketdata.universe import (
    CASH_SYMBOL,
    DEFAULT_UNIVERSE,
    UniverseInstrument,
    defensive_symbols,
    risk_symbols,
)

TRADING_DAYS_PER_YEAR = 252


class StrategyError(ValueError):
    """Raised for invalid strategy parameters or malformed contexts."""


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Prices visible at ``as_of`` plus universe roles.

    ``prices`` holds total-return adjusted closes, one column per symbol,
    with a tz-aware ``DatetimeIndex`` whose last label is ``<= as_of``.
    """

    prices: pd.DataFrame
    as_of: pd.Timestamp
    risk_symbols: tuple[str, ...]
    defensive_symbols: tuple[str, ...]
    cash_symbol: str | None

    def __post_init__(self) -> None:
        if len(self.prices.index) and self.prices.index[-1] > self.as_of:
            raise StrategyError("context prices extend beyond as_of (look-ahead)")

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(str(column) for column in self.prices.columns)

    def available(self, symbols: Sequence[str]) -> tuple[str, ...]:
        present = set(self.symbols)
        return tuple(symbol for symbol in symbols if symbol in present)

    def history_days(self, symbol: str) -> int:
        if symbol not in self.prices.columns:
            return 0
        return int(self.prices[symbol].dropna().shape[0])


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Catalog entry describing a strategy for the API and CLI."""

    name: str
    title: str
    description: str
    evidence: str
    default_params: Mapping[str, object] = field(default_factory=dict)
    is_benchmark: bool = False
    param_grid: Mapping[str, Sequence[object]] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "default_params": dict(self.default_params),
            "is_benchmark": self.is_benchmark,
            "param_grid": {
                key: list(values) for key, values in self.param_grid.items()
            },
        }


@runtime_checkable
class Strategy(Protocol):
    """Return target weights (0..1, sum <= 1) from a PIT context."""

    @property
    def name(self) -> str: ...

    def params(self) -> dict[str, object]: ...

    def warmup_days(self) -> int: ...

    def target_weights(self, context: StrategyContext) -> pd.Series: ...


def build_context(
    prices: pd.DataFrame,
    as_of: pd.Timestamp | None = None,
    *,
    universe: Sequence[UniverseInstrument] = DEFAULT_UNIVERSE,
    cash_symbol: str | None = CASH_SYMBOL,
) -> StrategyContext:
    """Slice ``prices`` to rows ``<= as_of`` and attach universe roles."""
    stamp = pd.Timestamp(prices.index[-1]) if as_of is None else pd.Timestamp(as_of)
    visible = prices.loc[prices.index <= stamp]
    present = {str(column) for column in visible.columns}
    risk = tuple(symbol for symbol in risk_symbols(universe) if symbol in present)
    defensive = tuple(
        symbol for symbol in defensive_symbols(universe) if symbol in present
    )
    cash = cash_symbol if cash_symbol in present else None
    return StrategyContext(
        prices=visible,
        as_of=stamp,
        risk_symbols=risk,
        defensive_symbols=defensive,
        cash_symbol=cash,
    )


def normalize_weights(
    weights: Mapping[str, float] | pd.Series,
    *,
    symbols: Sequence[str],
    cash_symbol: str | None = None,
) -> pd.Series:
    """Clip to long-only, cap gross at 1, park any remainder in cash."""
    series = pd.Series(dict(weights), dtype="float64")
    series = series.reindex(list(symbols)).fillna(0.0).clip(lower=0.0)
    gross = float(series.sum())
    if gross > 1.0:
        series = series / gross
        gross = 1.0
    if cash_symbol is not None and cash_symbol in series.index and gross < 1.0:
        series[cash_symbol] = float(series[cash_symbol]) + (1.0 - gross)
    return series.astype("float64")


def trailing_return(prices: pd.DataFrame, lookback_days: int) -> pd.Series:
    """Simple return over ``lookback_days`` sessions for each column."""
    if len(prices.index) <= lookback_days:
        return pd.Series(index=prices.columns, dtype="float64")
    last = prices.iloc[-1]
    first = prices.iloc[-1 - lookback_days]
    return (last / first) - 1.0


def trailing_volatility(prices: pd.DataFrame, lookback_days: int) -> pd.Series:
    """Annualized volatility of daily returns over ``lookback_days``."""
    window = prices.iloc[-(lookback_days + 1) :]
    daily = window.pct_change().dropna(how="all")
    annualized: pd.Series = daily.std(ddof=1) * (TRADING_DAYS_PER_YEAR**0.5)
    return annualized
