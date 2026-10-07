"""Investable universe: liquid US ETFs across asset classes (+ optional BTC).

Chosen for diversification and liquidity, not for a prediction of returns.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

ASSET_CLASS_ETF = "etf"
ASSET_CLASS_CRYPTO = "crypto"

ROLE_RISK = "risk"
ROLE_DEFENSIVE = "defensive"
ROLE_CASH = "cash"

DEFAULT_HISTORY_START = date(2005, 1, 1)


@dataclass(frozen=True, slots=True)
class UniverseInstrument:
    symbol: str
    name: str
    asset_class: str
    role: str
    category: str
    currency: str = "USD"

    def as_mapping(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "asset_class": self.asset_class,
            "role": self.role,
            "category": self.category,
            "currency": self.currency,
        }


DEFAULT_UNIVERSE: tuple[UniverseInstrument, ...] = (
    UniverseInstrument("SPY", "S&P 500", ASSET_CLASS_ETF, ROLE_RISK, "us_equity"),
    UniverseInstrument("QQQ", "Nasdaq 100", ASSET_CLASS_ETF, ROLE_RISK, "us_equity"),
    UniverseInstrument(
        "IWM", "Russell 2000 small caps", ASSET_CLASS_ETF, ROLE_RISK, "us_equity"
    ),
    UniverseInstrument(
        "EFA", "Developed markets ex-US", ASSET_CLASS_ETF, ROLE_RISK, "intl_equity"
    ),
    UniverseInstrument(
        "EEM", "Emerging markets", ASSET_CLASS_ETF, ROLE_RISK, "intl_equity"
    ),
    UniverseInstrument("VNQ", "US REITs", ASSET_CLASS_ETF, ROLE_RISK, "real_estate"),
    UniverseInstrument(
        "TLT", "20+ year Treasuries", ASSET_CLASS_ETF, ROLE_DEFENSIVE, "bonds"
    ),
    UniverseInstrument(
        "IEF", "7-10 year Treasuries", ASSET_CLASS_ETF, ROLE_DEFENSIVE, "bonds"
    ),
    UniverseInstrument("GLD", "Gold", ASSET_CLASS_ETF, ROLE_DEFENSIVE, "commodities"),
    UniverseInstrument(
        "DBC", "Broad commodities", ASSET_CLASS_ETF, ROLE_RISK, "commodities"
    ),
    UniverseInstrument(
        "BIL", "1-3 month T-bills (cash proxy)", ASSET_CLASS_ETF, ROLE_CASH, "cash"
    ),
)

OPTIONAL_UNIVERSE: tuple[UniverseInstrument, ...] = (
    UniverseInstrument("BTC-USD", "Bitcoin", ASSET_CLASS_CRYPTO, ROLE_RISK, "crypto"),
)

CASH_SYMBOL = "BIL"
BENCHMARK_SYMBOL = "SPY"
BOND_BENCHMARK_SYMBOL = "IEF"


def universe_symbols(
    instruments: Iterable[UniverseInstrument] = DEFAULT_UNIVERSE,
) -> tuple[str, ...]:
    return tuple(item.symbol for item in instruments)


def resolve_universe(
    symbols: Sequence[str] | None = None,
    *,
    include_optional: bool = False,
) -> tuple[UniverseInstrument, ...]:
    """Return universe rows for ``symbols`` (default universe when None)."""
    known = {item.symbol: item for item in DEFAULT_UNIVERSE + OPTIONAL_UNIVERSE}
    if symbols is None:
        selected = list(DEFAULT_UNIVERSE)
        if include_optional:
            selected.extend(OPTIONAL_UNIVERSE)
        return tuple(selected)
    resolved: list[UniverseInstrument] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        item = known.get(symbol)
        if item is None:
            asset_class = (
                ASSET_CLASS_CRYPTO if symbol.endswith("-USD") else ASSET_CLASS_ETF
            )
            item = UniverseInstrument(symbol, symbol, asset_class, ROLE_RISK, "custom")
        resolved.append(item)
    return tuple(resolved)


def risk_symbols(
    instruments: Iterable[UniverseInstrument] = DEFAULT_UNIVERSE,
) -> tuple[str, ...]:
    return tuple(item.symbol for item in instruments if item.role == ROLE_RISK)


def defensive_symbols(
    instruments: Iterable[UniverseInstrument] = DEFAULT_UNIVERSE,
) -> tuple[str, ...]:
    return tuple(item.symbol for item in instruments if item.role == ROLE_DEFENSIVE)
