"""Build deterministic point-in-time research datasets from stored silver rows."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from quant_platform.data.calendar import session_date_for_observation
from quant_platform.data.models import (
    CorporateAction,
    DailyBar,
    DataSource,
    Exchange,
    Instrument,
    MarketCalendar,
    MarketSession,
)
from quant_platform.data.repository import (
    get_market_calendar_by_code,
    list_market_sessions,
)
from quant_platform.data.validation import DataValidationError, validate_ohlc
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)


def list_instruments_for_dataset(
    session: Session, request: DailyBarsDatasetRequest
) -> tuple[tuple[Instrument, Exchange | None], ...]:
    """Return instruments matching the request identity filters.

    Used by dataset quality reports so instruments with zero bars still
    appear in coverage. ``allow_unfiltered`` without identity filters is
    the caller's problem; this returns every instrument in that case.
    """
    _ensure_validated_request(request)
    stmt: Select[Any] = (
        select(Instrument, Exchange)
        .outerjoin(Exchange, Instrument.exchange_id == Exchange.id)
        .order_by(Instrument.symbol, Instrument.asset_class, Instrument.id)
    )
    stmt = _instrument_filters(stmt, request)
    return tuple(session.execute(stmt).tuples().all())


def get_daily_bars_dataset(
    session: Session,
    request: DailyBarsDatasetRequest,
) -> DailyBarsDataset:
    """Return latest-available daily bars as of ``request.as_of``.

    Corporate actions are not applied. Future ``available_time`` values are
    excluded. Order is ``(symbol, exchange_code, instrument_id,
    observation_time, source_name)``.
    """
    _ensure_validated_request(request)
    calendar = _resolve_calendar(session, request)
    stmt = _daily_bars_pit_statement(request)
    fetched: list[DailyBarDatasetRow] = []
    for bar, instrument, source, exchange in session.execute(stmt).tuples():
        fetched.append(
            DailyBarDatasetRow(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                exchange_code=exchange.code if exchange is not None else None,
                asset_class=instrument.asset_class,
                currency=instrument.currency,
                observation_time=bar.observation_time,
                available_time=bar.available_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source_name=source.name,
                ingestion_run_id=bar.ingestion_run_id,
                is_correction=bar.is_correction,
                correction_reason=bar.correction_reason,
            )
        )
    if calendar is not None:
        fetched = _apply_calendar_filter(session, fetched, calendar=calendar)
    for row in fetched:
        validate_dataset_bar_row(row, request=request)
    fetched.sort(key=_daily_bar_sort_key)
    return DailyBarsDataset(request=request, rows=tuple(fetched))


def get_corporate_actions_for_dataset(
    session: Session,
    request: DailyBarsDatasetRequest,
) -> tuple[CorporateActionDatasetRow, ...]:
    """Return stored corporate actions visible at ``as_of``. Does not adjust OHLCV."""
    _ensure_validated_request(request)
    if request.uses_calendar():
        _resolve_calendar(session, request)
    stmt = _corporate_actions_statement(request)
    rows: list[CorporateActionDatasetRow] = []
    for action, instrument, exchange in session.execute(stmt).tuples():
        if action.available_time > request.as_of:
            raise DatasetValidationError(
                "corporate action available_time is after as_of",
                code=DatasetErrorCode.LOOKAHEAD,
            )
        if (
            action.effective_time < request.start_time
            or action.effective_time > request.end_time
        ):
            raise DatasetValidationError(
                "corporate action effective_time is outside the requested range",
                code=DatasetErrorCode.OUT_OF_RANGE,
            )
        rows.append(
            CorporateActionDatasetRow(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                exchange_code=exchange.code if exchange is not None else None,
                asset_class=instrument.asset_class,
                action_type=action.action_type,
                effective_time=action.effective_time,
                available_time=action.available_time,
                quantity_before=action.quantity_before,
                quantity_after=action.quantity_after,
                cash_amount=action.cash_amount,
                currency=action.currency,
                old_value=action.old_value,
                new_value=action.new_value,
                note=action.note,
            )
        )
    rows.sort(key=_corporate_action_sort_key)
    return tuple(rows)


def validate_dataset_bar_row(
    row: DailyBarDatasetRow, *, request: DailyBarsDatasetRequest
) -> None:
    """Post-query invariants. SQL already filters; this catches leakage."""
    if row.observation_time.tzinfo is None or row.available_time.tzinfo is None:
        raise DatasetValidationError(
            "dataset row timestamps must be timezone-aware",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    if row.available_time > request.as_of:
        raise DatasetValidationError(
            "available_time must be <= as_of",
            code=DatasetErrorCode.LOOKAHEAD,
        )
    if (
        row.observation_time < request.start_time
        or row.observation_time > request.end_time
    ):
        raise DatasetValidationError(
            "observation_time is outside the requested range",
            code=DatasetErrorCode.OUT_OF_RANGE,
        )
    try:
        validate_ohlc(row.open, row.high, row.low, row.close, row.volume)
    except DataValidationError as exc:
        raise DatasetValidationError(
            str(exc), code=DatasetErrorCode.INVALID_OHLC
        ) from exc


def _daily_bar_sort_key(row: DailyBarDatasetRow) -> tuple[object, ...]:
    return (
        row.symbol,
        row.exchange_code or "",
        str(row.instrument_id),
        row.observation_time,
        row.source_name,
    )


def _corporate_action_sort_key(row: CorporateActionDatasetRow) -> tuple[object, ...]:
    return (
        row.symbol,
        row.exchange_code or "",
        str(row.instrument_id),
        row.effective_time,
        row.available_time,
        row.action_type,
    )


def _ensure_validated_request(request: DailyBarsDatasetRequest) -> None:
    rebuilt = build_daily_bars_dataset_request(
        as_of=request.as_of,
        start_time=request.start_time,
        end_time=request.end_time,
        symbols=request.symbols,
        instrument_ids=request.instrument_ids,
        exchange_codes=request.exchange_codes,
        asset_classes=request.asset_classes,
        currency=request.currency,
        calendar_code=request.calendar_code,
        require_open_session=request.require_open_session,
        allow_unfiltered=request.allow_unfiltered,
    )
    if rebuilt != request:
        raise DatasetValidationError(
            "DailyBarsDatasetRequest must be built via "
            "build_daily_bars_dataset_request",
            code=DatasetErrorCode.INVALID_RANGE,
        )


def _resolve_calendar(
    session: Session, request: DailyBarsDatasetRequest
) -> MarketCalendar | None:
    if not request.uses_calendar():
        return None
    if request.calendar_code is None:
        raise DatasetValidationError(
            "require_open_session needs calendar_code; calendars are not inferred",
            code=DatasetErrorCode.CALENDAR_REQUIRED,
        )
    calendar = get_market_calendar_by_code(session, code=request.calendar_code)
    if calendar is None:
        raise DatasetValidationError(
            f"unknown calendar {request.calendar_code!r}",
            code=DatasetErrorCode.UNKNOWN_CALENDAR,
        )
    return calendar


def _instrument_filters(
    stmt: Select[Any], request: DailyBarsDatasetRequest
) -> Select[Any]:
    if request.symbols is not None:
        stmt = stmt.where(Instrument.symbol.in_(request.symbols))
    if request.instrument_ids is not None:
        stmt = stmt.where(Instrument.id.in_(request.instrument_ids))
    if request.exchange_codes is not None:
        stmt = stmt.where(Exchange.code.in_(request.exchange_codes))
    if request.asset_classes is not None:
        stmt = stmt.where(Instrument.asset_class.in_(request.asset_classes))
    if request.currency is not None:
        stmt = stmt.where(Instrument.currency == request.currency)
    return stmt


def _daily_bars_pit_statement(
    request: DailyBarsDatasetRequest,
) -> Select[Any]:
    stmt: Select[Any] = (
        select(DailyBar, Instrument, DataSource, Exchange)
        .join(Instrument, DailyBar.instrument_id == Instrument.id)
        .join(DataSource, DailyBar.source_id == DataSource.id)
        .outerjoin(Exchange, Instrument.exchange_id == Exchange.id)
        .where(DailyBar.available_time <= request.as_of)
        .where(DailyBar.observation_time >= request.start_time)
        .where(DailyBar.observation_time <= request.end_time)
        .distinct(DailyBar.instrument_id, DailyBar.source_id, DailyBar.observation_time)
        .order_by(
            DailyBar.instrument_id,
            DailyBar.source_id,
            DailyBar.observation_time,
            DailyBar.available_time.desc(),
        )
    )
    return _instrument_filters(stmt, request)


def _corporate_actions_statement(
    request: DailyBarsDatasetRequest,
) -> Select[Any]:
    stmt: Select[Any] = (
        select(CorporateAction, Instrument, Exchange)
        .join(Instrument, CorporateAction.instrument_id == Instrument.id)
        .outerjoin(Exchange, Instrument.exchange_id == Exchange.id)
        .where(CorporateAction.available_time <= request.as_of)
        .where(CorporateAction.effective_time >= request.start_time)
        .where(CorporateAction.effective_time <= request.end_time)
        .order_by(
            Instrument.symbol,
            CorporateAction.effective_time,
            CorporateAction.available_time,
        )
    )
    return _instrument_filters(stmt, request)


def _apply_calendar_filter(
    session: Session,
    rows: list[DailyBarDatasetRow],
    *,
    calendar: MarketCalendar,
) -> list[DailyBarDatasetRow]:
    sessions: dict[date, MarketSession] = {
        item.session_date: item
        for item in list_market_sessions(session, calendar_id=calendar.id)
    }
    missing: list[date] = []
    kept: list[DailyBarDatasetRow] = []
    for row in rows:
        session_date = session_date_for_observation(
            row.observation_time, calendar.timezone
        )
        market_session = sessions.get(session_date)
        if market_session is None:
            missing.append(session_date)
            continue
        if not market_session.is_open:
            continue
        kept.append(row)
    if missing:
        listed = ", ".join(item.isoformat() for item in sorted(set(missing)))
        raise DatasetValidationError(
            f"calendar {calendar.code!r} has no session row for {listed}",
            code=DatasetErrorCode.INCOMPLETE_CALENDAR,
        )
    return kept
