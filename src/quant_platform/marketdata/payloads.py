"""Map vendor history frames to contract payload batches with PIT timestamps.

Conventions (documented in docs/trading/MARKET_DATA.md):

- A daily bar for session date ``D`` has ``observation_time`` at the
  session close and ``available_time`` one hour later. Bars whose
  ``available_time`` is after ``now`` are dropped (incomplete sessions).
- Yahoo prices are already split-adjusted, so splits are **not** emitted
  as corporate actions (they would double-adjust). Dividends are emitted
  as ``dividend`` actions on the ex-date.
- OHLC bounds are sanitized (``high >= max(open, close)``,
  ``low <= min(open, close)``) and the fix is recorded in metadata.
- A bar that differs from the stored one for the same session is emitted
  as a correction with ``available_time = now`` (vendor restatement).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import pandas as pd

from quant_platform.data.contracts.types import (
    DataSourceContract,
    DataSourceKind,
    DataVendorCapability,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorPayloadBatch,
)
from quant_platform.marketdata.universe import ASSET_CLASS_CRYPTO

PRICE_QUANTUM = Decimal("0.00000001")
VOLUME_QUANTUM = Decimal("1")
DIVIDEND_QUANTUM = Decimal("0.00000001")
RESTATEMENT_TOLERANCE = Decimal("0.000001")

# Session close / availability per asset class (UTC).
_EQUITY_CLOSE = time(21, 0)
_EQUITY_AVAILABLE_DELAY = timedelta(hours=1)
_CRYPTO_CLOSE = time(23, 59)
_CRYPTO_AVAILABLE_DELAY = timedelta(minutes=31)
_DIVIDEND_EFFECTIVE = time(13, 30)
_DIVIDEND_AVAILABLE_DELAY = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class StoredBarSnapshot:
    """Minimal view of a stored silver bar used to detect restatements."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketDataPayloadReport:
    symbol: str
    rows_received: int
    bars_emitted: int
    bars_dropped_incomplete: int
    bars_dropped_invalid: int
    bars_unchanged: int
    corrections_emitted: int
    dividends_emitted: int
    splits_seen: int
    sanitized_bars: int
    first_session: date | None
    last_session: date | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "rows_received": self.rows_received,
            "bars_emitted": self.bars_emitted,
            "bars_dropped_incomplete": self.bars_dropped_incomplete,
            "bars_dropped_invalid": self.bars_dropped_invalid,
            "bars_unchanged": self.bars_unchanged,
            "corrections_emitted": self.corrections_emitted,
            "dividends_emitted": self.dividends_emitted,
            "splits_seen": self.splits_seen,
            "sanitized_bars": self.sanitized_bars,
            "first_session": None
            if self.first_session is None
            else self.first_session.isoformat(),
            "last_session": None
            if self.last_session is None
            else self.last_session.isoformat(),
        }


def market_data_contract(source_name: str) -> DataSourceContract:
    return DataSourceContract(
        source_name=source_name,
        source_kind=DataSourceKind.VENDOR_API.value,
        capabilities=(
            DataVendorCapability.DAILY_BARS,
            DataVendorCapability.CORPORATE_ACTIONS,
        ),
        requires_network=True,
        requires_credentials=False,
        pit_required=True,
        capture_raw_payload=True,
    )


def session_times(session_date: date, *, asset_class: str) -> tuple[datetime, datetime]:
    """Return ``(observation_time, available_time)`` for a session date."""
    if asset_class == ASSET_CLASS_CRYPTO:
        observation = datetime.combine(session_date, _CRYPTO_CLOSE, tzinfo=UTC)
        return observation, observation + _CRYPTO_AVAILABLE_DELAY
    observation = datetime.combine(session_date, _EQUITY_CLOSE, tzinfo=UTC)
    return observation, observation + _EQUITY_AVAILABLE_DELAY


def dividend_times(ex_date: date) -> tuple[datetime, datetime]:
    effective = datetime.combine(ex_date, _DIVIDEND_EFFECTIVE, tzinfo=UTC)
    return effective, effective + _DIVIDEND_AVAILABLE_DELAY


def build_market_data_batch(
    frame: pd.DataFrame,
    *,
    symbol: str,
    source_name: str,
    asset_class: str,
    now: datetime,
    stored_bars: Mapping[date, StoredBarSnapshot] | None = None,
    stored_dividend_dates: frozenset[date] | set[date] | None = None,
) -> tuple[VendorPayloadBatch, MarketDataPayloadReport]:
    """Convert one symbol's history frame into a validated-shape batch."""
    ingestion_time = _utc(now)
    stored = dict(stored_bars or {})
    known_dividends = set(stored_dividend_dates or ())
    bars: list[VendorDailyBarPayload] = []
    actions: list[VendorCorporateActionPayload] = []
    dropped_incomplete = 0
    dropped_invalid = 0
    unchanged = 0
    corrections = 0
    sanitized = 0
    splits_seen = 0
    first: date | None = None
    last: date | None = None

    for timestamp, row in frame.iterrows():
        session_date = _session_date(timestamp)
        observation, available = session_times(session_date, asset_class=asset_class)
        split_ratio = _float(row.get("Stock Splits"))
        if split_ratio and split_ratio != 1.0:
            splits_seen += 1
        dividend = _float(row.get("Dividends"))
        if dividend and dividend > 0 and session_date not in known_dividends:
            effective, div_available = dividend_times(session_date)
            if div_available <= ingestion_time:
                actions.append(
                    VendorCorporateActionPayload(
                        symbol=symbol,
                        source_name=source_name,
                        action_type="dividend",
                        effective_time=effective,
                        available_time=div_available,
                        observation_time=effective,
                        ingestion_time=ingestion_time,
                        cash_amount=_decimal(dividend, DIVIDEND_QUANTUM),
                        currency="USD",
                        note="cash dividend per share on ex-date",
                        raw_payload={
                            "Date": session_date.isoformat(),
                            "Dividends": dividend,
                        },
                    )
                )
        prices = _prices(row)
        if prices is None:
            dropped_invalid += 1
            continue
        if available > ingestion_time:
            dropped_incomplete += 1
            continue
        open_, high, low, close, volume, was_sanitized = prices
        if was_sanitized:
            sanitized += 1
        is_correction = False
        existing = stored.get(session_date)
        if existing is not None:
            if _same_bar(existing, open_, high, low, close, volume):
                unchanged += 1
                continue
            is_correction = True
            corrections += 1
            available = ingestion_time
        metadata: dict[str, object] = {"session_date": session_date.isoformat()}
        if was_sanitized:
            metadata["sanitized"] = "ohlc_bounds"
        bars.append(
            VendorDailyBarPayload(
                symbol=symbol,
                source_name=source_name,
                observation_time=observation,
                available_time=available,
                ingestion_time=ingestion_time,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                raw_payload=_raw_payload(session_date, row),
                metadata=metadata,
                is_correction=is_correction,
                correction_reason="vendor_restatement" if is_correction else None,
            )
        )
        first = session_date if first is None else min(first, session_date)
        last = session_date if last is None else max(last, session_date)

    batch = VendorPayloadBatch(
        source_name=source_name,
        contract=market_data_contract(source_name),
        daily_bars=tuple(bars),
        corporate_actions=tuple(actions),
    )
    report = MarketDataPayloadReport(
        symbol=symbol,
        rows_received=len(frame),
        bars_emitted=len(bars),
        bars_dropped_incomplete=dropped_incomplete,
        bars_dropped_invalid=dropped_invalid,
        bars_unchanged=unchanged,
        corrections_emitted=corrections,
        dividends_emitted=len(actions),
        splits_seen=splits_seen,
        sanitized_bars=sanitized,
        first_session=first,
        last_session=last,
    )
    return batch, report


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _session_date(timestamp: object) -> date:
    stamp = pd.Timestamp(timestamp)  # type: ignore[arg-type]
    if stamp.tzinfo is not None:
        # Yahoo indexes daily bars at local midnight; converting to UTC may
        # shift the civil date (e.g. 04:00Z for New York). Use the vendor's
        # local civil date when available.
        local = stamp.tz_convert("America/New_York")
        if local.hour <= 12:
            return local.date()
    return stamp.date()


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _decimal(value: float, quantum: Decimal) -> Decimal:
    return Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)


def _prices(
    row: pd.Series,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal | None, bool] | None:
    open_ = _float(row.get("Open"))
    high = _float(row.get("High"))
    low = _float(row.get("Low"))
    close = _float(row.get("Close"))
    if open_ is None or high is None or low is None or close is None:
        return None
    if min(open_, high, low, close) <= 0:
        return None
    sanitized = False
    top = max(open_, close)
    bottom = min(open_, close)
    if high < top:
        high = top
        sanitized = True
    if low > bottom:
        low = bottom
        sanitized = True
    volume_raw = _float(row.get("Volume"))
    volume = (
        None
        if volume_raw is None or volume_raw < 0
        else _decimal(volume_raw, VOLUME_QUANTUM)
    )
    return (
        _decimal(open_, PRICE_QUANTUM),
        _decimal(high, PRICE_QUANTUM),
        _decimal(low, PRICE_QUANTUM),
        _decimal(close, PRICE_QUANTUM),
        volume,
        sanitized,
    )


def _same_bar(
    existing: StoredBarSnapshot,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal | None,
) -> bool:
    for stored, fetched in (
        (existing.open, open_),
        (existing.high, high),
        (existing.low, low),
        (existing.close, close),
    ):
        if stored == 0:
            if fetched != 0:
                return False
            continue
        if abs(stored - fetched) / abs(stored) > RESTATEMENT_TOLERANCE:
            return False
    if existing.volume is None or volume is None:
        return True
    if existing.volume == 0:
        return volume == 0
    # Volume is revised frequently by Yahoo; only large changes count.
    return abs(existing.volume - volume) / existing.volume <= Decimal("0.05")


def _raw_payload(session_date: date, row: pd.Series) -> dict[str, object]:
    payload: dict[str, object] = {"Date": session_date.isoformat()}
    for key in ("Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"):
        value = _float(row.get(key))
        payload[key] = value
    return payload
