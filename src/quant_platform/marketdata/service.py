"""Fetch real daily history and store it through contract payload intake.

Each symbol becomes one ``VendorPayloadBatch`` and one ingestion run:
bronze raw records first, then idempotent silver ``daily_bars`` and
``corporate_actions``. Existing rows are never updated or deleted;
vendor restatements arrive as new PIT rows (corrections).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.core.time import utc_now
from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_request,
    execute_contract_payload_intake,
)
from quant_platform.data.models import CorporateAction, DailyBar, DataSource, Instrument
from quant_platform.data.repository import upsert_data_source
from quant_platform.marketdata.payloads import (
    MarketDataPayloadReport,
    StoredBarSnapshot,
    build_market_data_batch,
)
from quant_platform.marketdata.providers import (
    MarketDataProvider,
    MarketDataProviderError,
)
from quant_platform.marketdata.universe import (
    DEFAULT_HISTORY_START,
    DEFAULT_UNIVERSE,
    UniverseInstrument,
)

MARKET_DATA_VENDOR_LABEL = "yahoo_finance"
MARKET_DATA_CREATED_BY = "market_data_fetch"
INCREMENTAL_OVERLAP_DAYS = 10


@dataclass(frozen=True, slots=True)
class MarketDataSymbolReport:
    symbol: str
    asset_class: str
    status: str
    fetch_start: date | None
    payload: MarketDataPayloadReport | None
    inserted_daily_bars: int = 0
    inserted_corporate_actions: int = 0
    skipped_daily_bars: int = 0
    skipped_corporate_actions: int = 0
    intake_hash: str | None = None
    error: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "status": self.status,
            "fetch_start": None
            if self.fetch_start is None
            else self.fetch_start.isoformat(),
            "payload": None if self.payload is None else self.payload.as_mapping(),
            "inserted_daily_bars": self.inserted_daily_bars,
            "inserted_corporate_actions": self.inserted_corporate_actions,
            "skipped_daily_bars": self.skipped_daily_bars,
            "skipped_corporate_actions": self.skipped_corporate_actions,
            "intake_hash": self.intake_hash,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class MarketDataFetchReport:
    source_name: str
    provider: str
    write_db: bool
    started_at: datetime
    finished_at: datetime
    symbols: tuple[MarketDataSymbolReport, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(item.status != "error" for item in self.symbols)

    @property
    def inserted_daily_bars(self) -> int:
        return sum(item.inserted_daily_bars for item in self.symbols)

    @property
    def inserted_corporate_actions(self) -> int:
        return sum(item.inserted_corporate_actions for item in self.symbols)

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "market_data_fetch_report",
            "ok": self.ok,
            "source_name": self.source_name,
            "provider": self.provider,
            "write_db": self.write_db,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "inserted_daily_bars": self.inserted_daily_bars,
            "inserted_corporate_actions": self.inserted_corporate_actions,
            "symbol_count": len(self.symbols),
            "error_count": sum(1 for item in self.symbols if item.status == "error"),
            "symbols": [item.as_mapping() for item in self.symbols],
        }


def fetch_and_store_market_data(
    session: Session,
    provider: MarketDataProvider,
    instruments: Sequence[UniverseInstrument] = DEFAULT_UNIVERSE,
    *,
    source_name: str,
    start: date = DEFAULT_HISTORY_START,
    end: date | None = None,
    now: datetime | None = None,
    write_db: bool = True,
    full_refresh: bool = False,
    commit: bool = True,
) -> MarketDataFetchReport:
    """Download history per symbol and write it through contract intake.

    ``write_db=False`` builds the plan only (dry-run). ``commit`` controls
    whether each symbol is committed; tests pass ``False`` and roll back.
    """
    started = utc_now()
    current = now.astimezone(UTC) if now is not None else started
    end_date = end if end is not None else current.date()
    if write_db:
        upsert_data_source(
            session,
            name=source_name,
            vendor=MARKET_DATA_VENDOR_LABEL,
            description="Yahoo Finance daily bars and dividends via yfinance",
        )
        session.flush()
    reports: list[MarketDataSymbolReport] = []
    for instrument in instruments:
        reports.append(
            _fetch_symbol(
                session,
                provider,
                instrument,
                source_name=source_name,
                start=start,
                end=end_date,
                now=current,
                write_db=write_db,
                full_refresh=full_refresh,
                commit=commit,
            )
        )
    return MarketDataFetchReport(
        source_name=source_name,
        provider=getattr(provider, "name", type(provider).__name__),
        write_db=write_db,
        started_at=started,
        finished_at=utc_now(),
        symbols=tuple(reports),
    )


def last_stored_session(
    session: Session, *, symbol: str, source_name: str
) -> date | None:
    """Latest stored session date for a symbol/source, or None."""
    stmt = (
        select(DailyBar.observation_time)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .join(DataSource, DataSource.id == DailyBar.source_id)
        .where(Instrument.symbol == symbol, DataSource.name == source_name)
        .order_by(DailyBar.observation_time.desc())
        .limit(1)
    )
    value = session.scalar(stmt)
    return None if value is None else value.astimezone(UTC).date()


def _fetch_symbol(
    session: Session,
    provider: MarketDataProvider,
    instrument: UniverseInstrument,
    *,
    source_name: str,
    start: date,
    end: date,
    now: datetime,
    write_db: bool,
    full_refresh: bool,
    commit: bool,
) -> MarketDataSymbolReport:
    symbol = instrument.symbol
    fetch_start = start
    stored_bars: dict[date, StoredBarSnapshot] = {}
    stored_dividends: set[date] = set()
    last_session = last_stored_session(session, symbol=symbol, source_name=source_name)
    if last_session is not None and not full_refresh:
        fetch_start = max(
            start, last_session - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
        )
    if last_session is not None:
        stored_bars = _stored_bars(
            session, symbol=symbol, source_name=source_name, since=fetch_start
        )
        stored_dividends = _stored_dividend_dates(
            session, symbol=symbol, since=fetch_start
        )
    if fetch_start > end:
        return MarketDataSymbolReport(
            symbol=symbol,
            asset_class=instrument.asset_class,
            status="up_to_date",
            fetch_start=fetch_start,
            payload=None,
        )
    try:
        frame = provider.fetch_history(symbol, start=fetch_start, end=end)
    except MarketDataProviderError as exc:
        return MarketDataSymbolReport(
            symbol=symbol,
            asset_class=instrument.asset_class,
            status="error",
            fetch_start=fetch_start,
            payload=None,
            error=str(exc),
        )
    batch, payload_report = build_market_data_batch(
        frame,
        symbol=symbol,
        source_name=source_name,
        asset_class=instrument.asset_class,
        now=now,
        stored_bars=stored_bars,
        stored_dividend_dates=stored_dividends,
    )
    if not batch.daily_bars and not batch.corporate_actions:
        return MarketDataSymbolReport(
            symbol=symbol,
            asset_class=instrument.asset_class,
            status="up_to_date",
            fetch_start=fetch_start,
            payload=payload_report,
        )
    request = build_contract_payload_intake_request(
        source_name=source_name,
        created_by=MARKET_DATA_CREATED_BY,
        write_db=write_db,
        asset_class=instrument.asset_class,
    )
    if not write_db:
        plan = build_contract_payload_intake_plan(batch, request)
        return MarketDataSymbolReport(
            symbol=symbol,
            asset_class=instrument.asset_class,
            status="planned" if plan.ok else "invalid",
            fetch_start=fetch_start,
            payload=payload_report,
            intake_hash=plan.intake_hash,
            error=None if plan.ok else _first_issue(plan.issues),
        )
    try:
        report = execute_contract_payload_intake(session, batch, request)
        if commit:
            session.commit()
    except Exception as exc:
        session.rollback()
        return MarketDataSymbolReport(
            symbol=symbol,
            asset_class=instrument.asset_class,
            status="error",
            fetch_start=fetch_start,
            payload=payload_report,
            error=f"intake failed: {type(exc).__name__}",
        )
    status = "written" if report.db_executed else "invalid"
    return MarketDataSymbolReport(
        symbol=symbol,
        asset_class=instrument.asset_class,
        status=status,
        fetch_start=fetch_start,
        payload=payload_report,
        inserted_daily_bars=report.inserted_counts.daily_bars,
        inserted_corporate_actions=report.inserted_counts.corporate_actions,
        skipped_daily_bars=report.skipped_counts.daily_bars,
        skipped_corporate_actions=report.skipped_counts.corporate_actions,
        intake_hash=report.intake_hash,
        error=None if report.db_executed else _first_issue(report.issues),
    )


def _first_issue(issues: Sequence[object]) -> str | None:
    for item in issues:
        code = getattr(item, "code", None)
        message = getattr(item, "message", None)
        if code is not None:
            return f"{code}: {message}"
    return None


def _stored_bars(
    session: Session, *, symbol: str, source_name: str, since: date
) -> dict[date, StoredBarSnapshot]:
    since_time = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(DailyBar)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .join(DataSource, DataSource.id == DailyBar.source_id)
        .where(
            Instrument.symbol == symbol,
            DataSource.name == source_name,
            DailyBar.observation_time >= since_time,
        )
        .order_by(DailyBar.observation_time, DailyBar.available_time)
    )
    latest: dict[date, StoredBarSnapshot] = {}
    for bar in session.scalars(stmt):
        key = bar.observation_time.astimezone(UTC).date()
        latest[key] = StoredBarSnapshot(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
    return latest


def _stored_dividend_dates(session: Session, *, symbol: str, since: date) -> set[date]:
    since_time = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(CorporateAction.effective_time)
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(
            Instrument.symbol == symbol,
            CorporateAction.action_type == "dividend",
            CorporateAction.effective_time >= since_time,
        )
    )
    return {value.astimezone(UTC).date() for value in session.scalars(stmt)}
