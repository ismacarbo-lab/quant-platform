"""Market data providers. Only this module may import the vendor SDK.

``YFinanceMarketDataProvider`` talks to Yahoo Finance (no account, no API
key). ``RecordedMarketDataProvider`` replays CSV fixtures so tests and CI
stay offline.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

HISTORY_COLUMNS: tuple[str, ...] = (
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Dividends",
    "Stock Splits",
)


class MarketDataProviderError(RuntimeError):
    """Raised when a provider cannot return a usable history frame."""


class MarketDataProvider(Protocol):
    """Return daily history for one symbol.

    The frame must have a tz-aware ``DatetimeIndex`` and the columns in
    :data:`HISTORY_COLUMNS`. Prices are whatever the vendor reports as raw
    (Yahoo reports split-adjusted prices and split-adjusted dividends).
    """

    name: str

    def fetch_history(self, symbol: str, *, start: date, end: date) -> pd.DataFrame: ...


def normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce a vendor frame to the canonical column set and a UTC index."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(HISTORY_COLUMNS))
    working = frame.copy()
    if isinstance(working.columns, pd.MultiIndex):
        working.columns = [str(col[0]) for col in working.columns]
    rename = {str(col): str(col).strip() for col in working.columns}
    working = working.rename(columns=rename)
    for column in HISTORY_COLUMNS:
        if column not in working.columns:
            working[column] = 0.0 if column in ("Dividends", "Stock Splits") else pd.NA
    working = working[list(HISTORY_COLUMNS)]
    index = pd.DatetimeIndex(pd.to_datetime(working.index))
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    working.index = index
    working = working[~working.index.duplicated(keep="last")].sort_index()
    return working


class YFinanceMarketDataProvider:
    """Yahoo Finance daily history through the ``yfinance`` package."""

    name = "yfinance"

    def __init__(self, *, auto_adjust: bool = False) -> None:
        self._auto_adjust = auto_adjust

    def fetch_history(self, symbol: str, *, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf  # lazy: keeps app start-up and tests offline

        ticker = yf.Ticker(symbol)
        try:
            frame = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=self._auto_adjust,
                actions=True,
                raise_errors=True,
            )
        except Exception as exc:  # vendor errors are not typed
            raise MarketDataProviderError(
                f"yfinance history failed for {symbol}: {type(exc).__name__}"
            ) from exc
        if frame is None or frame.empty:
            raise MarketDataProviderError(f"yfinance returned no rows for {symbol}")
        return normalize_history_frame(frame)


class RecordedMarketDataProvider:
    """Offline provider reading ``<dir>/<SYMBOL>.csv`` recorded histories."""

    name = "recorded"

    def __init__(
        self,
        fixtures_dir: Path | str,
        *,
        frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> None:
        self._dir = Path(fixtures_dir)
        self._frames = dict(frames or {})
        self.calls: list[tuple[str, date, date]] = []

    def fetch_history(self, symbol: str, *, start: date, end: date) -> pd.DataFrame:
        self.calls.append((symbol, start, end))
        if symbol in self._frames:
            frame = self._frames[symbol]
        else:
            path = self._dir / f"{symbol}.csv"
            if not path.is_file():
                raise MarketDataProviderError(f"no recorded history for {symbol}")
            frame = pd.read_csv(path, index_col=0)
        normalized = normalize_history_frame(frame)
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        return normalized[(normalized.index >= start_ts) & (normalized.index < end_ts)]
