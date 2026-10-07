"""Point-in-time price panels for backtests (total-return adjusted).

Reads silver ``daily_bars`` and ``corporate_actions`` visible at ``as_of``
and applies the same dividend math as the ``total_return`` normalization
mode, vectorized with pandas. Silver rows are never modified.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.data.models import CorporateAction, DailyBar, DataSource, Instrument


class PricePanelError(ValueError):
    """Raised when the panel cannot be built (no data, bad window)."""


@dataclass(frozen=True, slots=True)
class PricePanel:
    """Daily session panel: adjusted closes/opens plus raw prices.

    ``closes``/``opens`` are total-return adjusted (for signals and
    backtests). ``raw_closes``/``raw_opens`` are the traded prices (for
    paper fills). ``dividends`` holds PIT-visible cash dividends per symbol.
    """

    closes: pd.DataFrame
    opens: pd.DataFrame
    raw_closes: pd.DataFrame
    raw_opens: pd.DataFrame
    source_name: str
    as_of: pd.Timestamp
    data_hash: str
    dividends: Mapping[str, tuple[tuple[pd.Timestamp, float], ...]] = field(
        default_factory=dict
    )

    def dividends_on(self, session: pd.Timestamp) -> dict[str, float]:
        """Cash per share for symbols whose ex-date falls on ``session``."""
        day = pd.Timestamp(session).normalize()
        out: dict[str, float] = {}
        for symbol, events in self.dividends.items():
            total = sum(cash for ex_time, cash in events if ex_time.normalize() == day)
            if total > 0:
                out[symbol] = total
        return out

    def truncated(self, end: pd.Timestamp) -> PricePanel:
        """Panel restricted to sessions ``<= end`` (for replays)."""
        stamp = pd.Timestamp(end)
        keep = self.closes.index <= stamp
        return PricePanel(
            closes=self.closes.loc[keep],
            opens=self.opens.loc[keep],
            raw_closes=self.raw_closes.loc[keep],
            raw_opens=self.raw_opens.loc[keep],
            source_name=self.source_name,
            as_of=min(self.as_of, stamp + pd.Timedelta(hours=23)),
            data_hash=self.data_hash,
            dividends=self.dividends,
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(str(column) for column in self.closes.columns)

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.closes.index[0])

    @property
    def end(self) -> pd.Timestamp:
        return pd.Timestamp(self.closes.index[-1])

    @property
    def session_count(self) -> int:
        return len(self.closes.index)

    def coverage(self) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for symbol in self.symbols:
            series = self.closes[symbol].dropna()
            out[symbol] = {
                "sessions": int(series.shape[0]),
                "first": None if series.empty else str(series.index[0].date()),
                "last": None if series.empty else str(series.index[-1].date()),
            }
        return out


def load_price_panel(
    session: Session,
    *,
    source_name: str,
    symbols: Sequence[str],
    start: date,
    end: date,
    as_of: datetime | None = None,
) -> PricePanel:
    """Load the PIT panel from PostgreSQL. ``as_of`` defaults to now."""
    if not symbols:
        raise PricePanelError("at least one symbol is required")
    if start > end:
        raise PricePanelError("start must be <= end")
    stamp = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    start_time = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    end_time = datetime.combine(end, datetime.max.time(), tzinfo=UTC)
    bars_stmt = (
        select(
            Instrument.symbol,
            DailyBar.observation_time,
            DailyBar.available_time,
            DailyBar.open,
            DailyBar.close,
        )
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .join(DataSource, DataSource.id == DailyBar.source_id)
        .where(
            DataSource.name == source_name,
            Instrument.symbol.in_(list(symbols)),
            DailyBar.available_time <= stamp,
            DailyBar.observation_time >= start_time,
            DailyBar.observation_time <= end_time,
        )
        .order_by(Instrument.symbol, DailyBar.observation_time, DailyBar.available_time)
    )
    rows = session.execute(bars_stmt).all()
    if not rows:
        raise PricePanelError("no daily bars visible for the requested window")
    bars = pd.DataFrame(
        rows, columns=["symbol", "observation_time", "available_time", "open", "close"]
    )
    # Latest PIT version per (symbol, session): rows are ordered by
    # available_time so keep="last" picks the newest correction.
    bars["session"] = pd.to_datetime(bars["observation_time"], utc=True).dt.normalize()
    bars = bars.drop_duplicates(subset=["symbol", "session"], keep="last")
    bars["open"] = bars["open"].astype("float64")
    bars["close"] = bars["close"].astype("float64")
    raw_closes = bars.pivot(
        index="session", columns="symbol", values="close"
    ).sort_index()
    raw_opens = bars.pivot(
        index="session", columns="symbol", values="open"
    ).sort_index()
    raw_closes = raw_closes.reindex(columns=list(symbols))
    raw_opens = raw_opens.reindex(columns=list(symbols))

    dividends_stmt = (
        select(
            Instrument.symbol,
            CorporateAction.effective_time,
            CorporateAction.cash_amount,
        )
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(
            Instrument.symbol.in_(list(symbols)),
            CorporateAction.action_type == "dividend",
            CorporateAction.available_time <= stamp,
            CorporateAction.cash_amount.is_not(None),
        )
    )
    dividend_rows = session.execute(dividends_stmt).all()
    dividends: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for symbol, effective_time, cash in dividend_rows:
        dividends.setdefault(str(symbol), []).append(
            (pd.Timestamp(effective_time).tz_convert("UTC"), float(cash))
        )
    return panel_from_frames(
        raw_closes,
        raw_opens,
        dividends=dividends,
        source_name=source_name,
        as_of=pd.Timestamp(stamp),
    )


def panel_from_frames(
    raw_closes: pd.DataFrame,
    raw_opens: pd.DataFrame | None = None,
    *,
    dividends: Mapping[str, Sequence[tuple[pd.Timestamp, float]]] | None = None,
    source_name: str = "in_memory",
    as_of: pd.Timestamp | None = None,
) -> PricePanel:
    """Build a panel from frames (tests and offline fixtures)."""
    closes = raw_closes.sort_index().astype("float64")
    index = pd.DatetimeIndex(closes.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    closes.index = index.normalize()
    opens_source = raw_opens if raw_opens is not None else raw_closes
    opens = opens_source.sort_index().astype("float64")
    opens.index = closes.index
    opens = opens.reindex(columns=closes.columns)
    events = dividends or {}
    factors = total_return_factors(closes, events)
    adjusted_closes = closes * factors
    adjusted_opens = opens * factors
    stamp = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(closes.index[-1])
    frozen_dividends = {
        str(symbol): tuple(
            (pd.Timestamp(ex_time).tz_convert("UTC"), float(cash))
            for ex_time, cash in sorted(items, key=lambda item: item[0])
        )
        for symbol, items in events.items()
    }
    return PricePanel(
        closes=adjusted_closes,
        opens=adjusted_opens,
        raw_closes=closes,
        raw_opens=opens,
        source_name=source_name,
        as_of=stamp,
        data_hash=_panel_hash(closes, events),
        dividends=frozen_dividends,
    )


def total_return_factors(
    closes: pd.DataFrame,
    dividends: Mapping[str, Sequence[tuple[pd.Timestamp, float]]],
) -> pd.DataFrame:
    """Per-symbol multiplicative factors: bars before an ex-date are scaled by
    ``1 - D / P_prev`` for every later dividend (matches ``total_return``)."""
    factors = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
    for symbol in closes.columns:
        events = dividends.get(str(symbol))
        if not events:
            continue
        series = closes[symbol].dropna()
        if series.empty:
            continue
        per_session = pd.Series(1.0, index=series.index)
        tail = 1.0
        for ex_time, cash in events:
            ex_day = pd.Timestamp(ex_time).tz_convert("UTC").normalize()
            prior = series.loc[series.index < ex_day]
            if prior.empty or cash <= 0:
                continue
            prior_close = float(prior.iloc[-1])
            if prior_close <= 0:
                continue
            factor = 1.0 - cash / prior_close
            if factor <= 0:
                continue
            position = int(series.index.searchsorted(ex_day))
            if position >= len(series.index):
                # Ex-date after the last bar: every bar is "before" it.
                tail *= factor
                continue
            per_session.iloc[position] *= factor
        # adj[t] = product of factors for ex-dates strictly after session t.
        reverse_cumulative = per_session.iloc[::-1].cumprod().iloc[::-1]
        aligned = reverse_cumulative.shift(-1, fill_value=1.0) * tail
        factors.loc[aligned.index, symbol] = aligned.to_numpy()
    return factors


def _panel_hash(
    closes: pd.DataFrame,
    dividends: Mapping[str, Sequence[tuple[pd.Timestamp, float]]],
) -> str:
    payload = {
        "symbols": [str(column) for column in closes.columns],
        "sessions": len(closes.index),
        "first": None if closes.empty else str(closes.index[0].date()),
        "last": None if closes.empty else str(closes.index[-1].date()),
        "last_closes": {
            str(column): (
                None
                if closes[column].dropna().empty
                else format(Decimal(repr(float(closes[column].dropna().iloc[-1]))), "f")
            )
            for column in closes.columns
        },
        "dividend_counts": {
            str(symbol): len(events) for symbol, events in sorted(dividends.items())
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
