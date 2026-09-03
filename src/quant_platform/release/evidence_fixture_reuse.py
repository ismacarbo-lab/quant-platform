"""Read-only checks that existing PostgreSQL rows match evidence fixtures.

Does not insert, update, or delete. Silver daily_bars are never rewritten.
Not trading and not a PnL check.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.core.redact import redact_secret_text
from quant_platform.data.csv_loader import parse_observation_time, parse_utc_datetime
from quant_platform.data.models import (
    CorporateAction,
    DailyBar,
    DataSource,
    Instrument,
    MarketCalendar,
    MarketSession,
    session_kind_is_open,
)
from quant_platform.release.evidence_types import (
    EvidenceFixtureDataMode,
    EvidenceFixtureReuseIssue,
    EvidenceFixtureReuseReport,
    empty_fixture_reuse_report,
)

_DAILY_BARS_NAME = "daily_bars.csv"
_CORPORATE_ACTIONS_NAME = "corporate_actions.csv"
_SESSIONS_NAME = "sessions.csv"
_CORRECTIONS_NAME = "corrections.csv"

_BarKey = tuple[str, str, str]
_Ohlcv = tuple[Decimal, Decimal, Decimal, Decimal, Decimal | None]


def existing_fixture_daily_bars_present(
    session: Session,
    fixture_dir: Path,
    *,
    source_name: str,
) -> bool:
    """True when at least one non-correction bar exists for fixture symbols."""
    symbols = _fixture_symbols(fixture_dir)
    if not symbols:
        return False
    stmt = (
        select(DailyBar.id)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .join(DataSource, DataSource.id == DailyBar.source_id)
        .where(
            DataSource.name == source_name,
            Instrument.symbol.in_(symbols),
            DailyBar.is_correction.is_(False),
        )
        .limit(1)
    )
    return session.scalar(stmt) is not None


def check_existing_evidence_fixture_data(
    session: Session,
    fixture_dir: Path,
    *,
    source_name: str,
) -> EvidenceFixtureReuseReport:
    """Compare fixture CSVs with existing rows. Does not write."""
    issues: list[EvidenceFixtureReuseIssue] = []
    warnings: list[EvidenceFixtureReuseIssue] = []
    bars = verify_existing_daily_bars_match_fixture(
        session,
        fixture_dir,
        source_name=source_name,
        issues=issues,
        warnings=warnings,
    )
    actions = verify_existing_corporate_actions_match_fixture(
        session,
        fixture_dir,
        issues=issues,
        warnings=warnings,
    )
    sessions = verify_existing_sessions_match_fixture(
        session,
        fixture_dir,
        issues=issues,
        warnings=warnings,
    )
    error_issues = tuple(item for item in issues if item.severity == "error")
    ok = not error_issues
    mode = (
        EvidenceFixtureDataMode.REUSED.value
        if ok
        else EvidenceFixtureDataMode.FAILED.value
    )
    return empty_fixture_reuse_report(
        mode=mode,
        reused_bar_count=bars,
        reused_corporate_action_count=actions,
        reused_session_count=sessions,
        issues=error_issues,
        warnings=tuple(warnings),
    )


def verify_existing_daily_bars_match_fixture(
    session: Session,
    fixture_dir: Path,
    *,
    source_name: str,
    issues: list[EvidenceFixtureReuseIssue],
    warnings: list[EvidenceFixtureReuseIssue],
) -> int:
    """Match fixture originals (and optional corrections) without writing."""
    del warnings
    path = Path(fixture_dir) / _DAILY_BARS_NAME
    expected_rows = _read_daily_bar_fixture_rows(path)
    if not expected_rows:
        issues.append(
            _error("missing_fixture_bars", "daily_bars fixture has no data rows")
        )
        return 0

    source = session.scalar(select(DataSource).where(DataSource.name == source_name))
    if source is None:
        issues.append(
            _error(
                "missing_source",
                "data source for the evidence fixtures was not found",
            )
        )
        return 0

    symbols = tuple(sorted({row["symbol"] for row in expected_rows}))
    db_rows = session.execute(
        select(
            Instrument.symbol,
            DailyBar.observation_time,
            DailyBar.available_time,
            DailyBar.open,
            DailyBar.high,
            DailyBar.low,
            DailyBar.close,
            DailyBar.volume,
            DailyBar.is_correction,
        )
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .where(
            DailyBar.source_id == source.id,
            Instrument.symbol.in_(symbols),
        )
    ).all()
    originals: dict[_BarKey, _Ohlcv] = {}
    corrections: dict[_BarKey, _Ohlcv] = {}
    for row in db_rows:
        key = (
            str(row[0]),
            _dt_key(row[1]),
            _dt_key(row[2]),
        )
        values = (
            _as_decimal(row[3]),
            _as_decimal(row[4]),
            _as_decimal(row[5]),
            _as_decimal(row[6]),
            _as_decimal(row[7]) if row[7] is not None else None,
        )
        if bool(row[8]):
            corrections[key] = values
        else:
            originals[key] = values

    matched = 0
    seen_keys: set[tuple[str, str, str]] = set()
    for expected in expected_rows:
        key = (
            expected["symbol"],
            expected["observation_time"],
            expected["available_time"],
        )
        seen_keys.add(key)
        found = originals.get(key)
        if found is None:
            issues.append(
                _error(
                    "missing_bar",
                    "an original daily bar from the fixture is missing",
                )
            )
            continue
        if not _ohlcv_equal(found, cast(_Ohlcv, expected["ohlcv"])):
            issues.append(
                _error(
                    "bar_ohlcv_mismatch",
                    "an existing daily bar does not match the fixture OHLCV",
                )
            )
            continue
        matched += 1

    extra_originals = set(originals) - seen_keys
    if extra_originals:
        issues.append(
            _error(
                "extra_bar",
                "existing original daily bars are not equivalent to the fixture",
            )
        )

    correction_path = Path(fixture_dir) / _CORRECTIONS_NAME
    if correction_path.is_file():
        correction_rows = _read_daily_bar_fixture_rows(correction_path)
        for expected in correction_rows:
            key = (
                expected["symbol"],
                expected["observation_time"],
                expected["available_time"],
            )
            found = corrections.get(key)
            if found is None:
                issues.append(
                    _error(
                        "missing_correction",
                        "an existing correction bar does not match the fixture",
                    )
                )
                continue
            if not _ohlcv_equal(found, cast(_Ohlcv, expected["ohlcv"])):
                issues.append(
                    _error(
                        "correction_ohlcv_mismatch",
                        "an existing correction bar does not match the fixture OHLCV",
                    )
                )
    return matched


def verify_existing_corporate_actions_match_fixture(
    session: Session,
    fixture_dir: Path,
    *,
    issues: list[EvidenceFixtureReuseIssue],
    warnings: list[EvidenceFixtureReuseIssue],
) -> int:
    """Match stored corporate actions to the fixture CSV. No writes."""
    del warnings
    path = Path(fixture_dir) / _CORPORATE_ACTIONS_NAME
    expected_rows = _read_corporate_action_fixture_rows(path)
    expected_keys = Counter(row["key"] for row in expected_rows)
    symbols = tuple(sorted({row["symbol"] for row in expected_rows}))
    if not expected_rows:
        return 0
    db_rows = session.execute(
        select(
            Instrument.symbol,
            CorporateAction.action_type,
            CorporateAction.effective_time,
            CorporateAction.available_time,
            CorporateAction.quantity_before,
            CorporateAction.quantity_after,
            CorporateAction.cash_amount,
            CorporateAction.old_value,
            CorporateAction.new_value,
        )
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(Instrument.symbol.in_(symbols))
    ).all()
    actual_keys = Counter(
        (
            str(row[0]),
            str(row[1]),
            _dt_key(row[2]),
            _dt_key(row[3]),
            _decimal_key(row[4]),
            _decimal_key(row[5]),
            _decimal_key(row[6]),
            str(row[7] or ""),
            str(row[8] or ""),
        )
        for row in db_rows
    )
    matched = 0
    for key, count in expected_keys.items():
        actual = actual_keys.get(key, 0)
        if actual < count:
            issues.append(
                _error(
                    "corporate_action_mismatch",
                    "an existing corporate action does not match the fixture",
                )
            )
        else:
            matched += count
    extra = sum(actual_keys.values()) - matched
    if extra > 0:
        issues.append(
            _error(
                "extra_corporate_action",
                "existing corporate actions are not equivalent to the fixture",
            )
        )
    return matched


def verify_existing_sessions_match_fixture(
    session: Session,
    fixture_dir: Path,
    *,
    issues: list[EvidenceFixtureReuseIssue],
    warnings: list[EvidenceFixtureReuseIssue],
) -> int:
    """Match market_sessions to the fixture CSV. No writes."""
    del warnings
    path = Path(fixture_dir) / _SESSIONS_NAME
    expected_rows = _read_session_fixture_rows(path)
    if not expected_rows:
        return 0
    calendar_codes = tuple(sorted({row["calendar_code"] for row in expected_rows}))
    calendars = {
        row.code: row
        for row in session.scalars(
            select(MarketCalendar).where(MarketCalendar.code.in_(calendar_codes))
        )
    }
    matched = 0
    for calendar_code in calendar_codes:
        calendar = calendars.get(calendar_code)
        if calendar is None:
            issues.append(
                _error(
                    "missing_calendar",
                    "fixture calendar was not found",
                )
            )
            continue
        expected_for_calendar = [
            row for row in expected_rows if row["calendar_code"] == calendar_code
        ]
        db_sessions = list(
            session.scalars(
                select(MarketSession).where(MarketSession.calendar_id == calendar.id)
            )
        )
        by_date = {item.session_date: item for item in db_sessions}
        seen: set[date] = set()
        for expected in expected_for_calendar:
            session_date = cast(date, expected["session_date"])
            seen.add(session_date)
            found = by_date.get(session_date)
            if found is None:
                issues.append(
                    _error(
                        "missing_session",
                        "an existing market session does not match the fixture",
                    )
                )
                continue
            if not _session_equal(found, expected):
                issues.append(
                    _error(
                        "session_mismatch",
                        "an existing market session does not match the fixture",
                    )
                )
                continue
            matched += 1
        extra_dates = set(by_date) - seen
        if extra_dates:
            issues.append(
                _error(
                    "extra_session",
                    "existing market sessions are not equivalent to the fixture",
                )
            )
    return matched


def fixture_csv_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _read_daily_bar_fixture_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            symbol = (raw.get("symbol") or "").strip()
            observation = parse_observation_time(raw["date"])
            available = parse_utc_datetime(raw["available_time"], field="available_time")
            volume_raw = (raw.get("volume") or "").strip()
            rows.append(
                {
                    "symbol": symbol,
                    "observation_time": _dt_key(observation),
                    "available_time": _dt_key(available),
                    "ohlcv": (
                        _as_decimal(raw["open"]),
                        _as_decimal(raw["high"]),
                        _as_decimal(raw["low"]),
                        _as_decimal(raw["close"]),
                        _as_decimal(volume_raw) if volume_raw else None,
                    ),
                }
            )
    return rows


def _read_corporate_action_fixture_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            symbol = (raw.get("symbol") or "").strip()
            key = (
                symbol,
                (raw.get("action_type") or "").strip(),
                _dt_key(
                    parse_utc_datetime(raw["effective_time"], field="effective_time")
                ),
                _dt_key(
                    parse_utc_datetime(raw["available_time"], field="available_time")
                ),
                _decimal_key(_optional_decimal(raw.get("quantity_before"))),
                _decimal_key(_optional_decimal(raw.get("quantity_after"))),
                _decimal_key(_optional_decimal(raw.get("cash_amount"))),
                (raw.get("old_value") or "").strip(),
                (raw.get("new_value") or "").strip(),
            )
            rows.append({"symbol": symbol, "key": key})
    return rows


def _read_session_fixture_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            kind = (raw.get("session_kind") or "").strip()
            rows.append(
                {
                    "calendar_code": (raw.get("calendar_code") or "").strip(),
                    "session_date": date.fromisoformat(raw["session_date"].strip()),
                    "session_kind": kind,
                    "is_open": session_kind_is_open(kind),
                    "open_time": _parse_time(raw.get("open_time")),
                    "close_time": _parse_time(raw.get("close_time")),
                }
            )
    return rows


def _fixture_symbols(fixture_dir: Path) -> tuple[str, ...]:
    rows = _read_daily_bar_fixture_rows(Path(fixture_dir) / _DAILY_BARS_NAME)
    return tuple(sorted({str(item["symbol"]) for item in rows}))


def _session_equal(found: MarketSession, expected: dict[str, object]) -> bool:
    return (
        found.session_kind == expected["session_kind"]
        and found.is_open == expected["is_open"]
        and found.open_time == expected["open_time"]
        and found.close_time == expected["close_time"]
    )


def _ohlcv_equal(
    found: tuple[Decimal, Decimal, Decimal, Decimal, Decimal | None],
    expected: tuple[Decimal, Decimal, Decimal, Decimal, Decimal | None],
) -> bool:
    return (
        found[0] == expected[0]
        and found[1] == expected[1]
        and found[2] == expected[2]
        and found[3] == expected[3]
        and found[4] == expected[4]
    )


def _parse_time(value: str | None) -> time | None:
    raw = (value or "").strip()
    if not raw:
        return None
    return time.fromisoformat(raw)


def _optional_decimal(value: str | None) -> Decimal | None:
    raw = (value or "").strip()
    if not raw:
        return None
    return _as_decimal(raw)


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(redact_secret_text(f"invalid decimal {value!r}")) from exc


def _decimal_key(value: object) -> str:
    if value is None or str(value).strip() == "":
        return ""
    return format(_as_decimal(value), "f")


def _dt_key(value: object) -> str:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return stamp.astimezone(UTC).isoformat()
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _error(code: str, message: str) -> EvidenceFixtureReuseIssue:
    return EvidenceFixtureReuseIssue(
        severity="error",
        code=code,
        message=redact_secret_text(message),
    )
