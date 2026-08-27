"""Data-quality research policies. Stream audit only; never signals or PnL."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
from itertools import pairwise
from typing import Final

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
    OBSERVATION_KIND_CORPORATE_ACTION_SUMMARY,
    OBSERVATION_KIND_CORRECTION_SEEN,
    OBSERVATION_KIND_CORRECTION_SUMMARY,
    OBSERVATION_KIND_COVERAGE_GAP,
    OBSERVATION_KIND_COVERAGE_SUMMARY,
    OBSERVATION_KIND_DATA_QUALITY_SUMMARY,
    OBSERVATION_KIND_EVENT_SEEN,
    OBSERVATION_KIND_INSTRUMENT_SEEN,
    OBSERVATION_KIND_SESSION_SEEN,
    OBSERVATION_KIND_TEMPORAL_CONSISTENCY_WARNING,
    OBSERVATION_KIND_UNKNOWN_EVENT,
    PolicyRunOutput,
    ResearchObservation,
    ResearchObservationSummary,
    hash_policy_output,
    normalize_policy_config,
    sort_observations,
)
from quant_platform.backtest.types import (
    CORPORATE_ACTION_AUDIT_POLICY_NAME,
    CORRECTION_AUDIT_POLICY_NAME,
    COVERAGE_POLICY_NAME,
    DATA_QUALITY_POLICY_NAME,
)
from quant_platform.research.snapshots import canonical_datetime
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    EVENT_PRIORITY,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)

_ALLOWED_KINDS = frozenset(EVENT_PRIORITY)

_DATA_QUALITY_KEYS = frozenset(
    {
        "emit_event_observations",
        "emit_summary_observations",
        "max_observations",
    }
)
_COVERAGE_KEYS = frozenset(
    {
        "expected_instruments",
        "min_bars_per_instrument",
        "expected_dates",
        "expected_sessions",
        "max_gap_days",
    }
)
_CORPORATE_ACTION_KEYS = frozenset({"emit_each_action", "action_types"})
_CORRECTION_KEYS = frozenset({"emit_each_correction"})

_SESSION_OPEN: Final = "open"
_SESSION_HOLIDAY: Final = "holiday"
_SESSION_EXCEPTIONAL_CLOSE: Final = "exceptional_close"


class StreamAuditPolicy:
    """Shared event counters for research audit policies. Not a strategy."""

    name: str

    def __init__(self, *, name: str, config: Mapping[str, object]) -> None:
        self.name = name
        self._config = dict(config)
        self._event_count = 0
        self._market_event_count = 0
        self._session_event_count = 0
        self._corporate_action_event_count = 0
        self._started_event_seen = False
        self._finished_event_seen = False
        self._warnings: list[str] = []
        self._errors: list[str] = []
        self._observations: list[ResearchObservation] = []
        self._last_event_time: datetime | None = None
        self._out_of_sequence_count = 0
        self._unknown_event_count = 0
        self._kind_counts: Counter[str] = Counter()
        self._event_observation_count = 0
        self._max_observations: int | None = None

    def on_replay_started(self, event: ReplayStartedEvent) -> None:
        self._count(REPLAY_STARTED_KIND, event.event_time)
        self._started_event_seen = True

    def on_market_session(self, event: MarketSessionEvent) -> None:
        self._count(MARKET_SESSION_KIND, event.event_time)

    def on_corporate_action(self, event: CorporateActionEvent) -> None:
        self._count(CORPORATE_ACTION_KIND, event.event_time)

    def on_market_bar(self, event: MarketBarEvent) -> None:
        self._count(MARKET_BAR_KIND, event.event_time)

    def on_replay_finished(self, event: ReplayFinishedEvent) -> None:
        self._count(REPLAY_FINISHED_KIND, event.event_time)
        self._finished_event_seen = True

    def observe(self, event: ReplayEvent | str) -> None:
        if isinstance(event, ReplayStartedEvent):
            self.on_replay_started(event)
            return
        if isinstance(event, MarketSessionEvent):
            self.on_market_session(event)
            return
        if isinstance(event, CorporateActionEvent):
            self.on_corporate_action(event)
            return
        if isinstance(event, MarketBarEvent):
            self.on_market_bar(event)
            return
        if isinstance(event, ReplayFinishedEvent):
            self.on_replay_finished(event)
            return
        kind = event if isinstance(event, str) else event.kind
        self._count(kind, None)
        if kind not in _ALLOWED_KINDS:
            self._unknown_event_count += 1
            self._warnings.append(f"unknown_event:{kind}")
            stamp = self._last_event_time
            if stamp is not None:
                self._observe(
                    stamp,
                    kind=OBSERVATION_KIND_UNKNOWN_EVENT,
                    message="unrecognized replay event kind",
                    severity="warning",
                    metadata={"event_kind": kind},
                    limited=True,
                )

    def emitted_orders(self) -> tuple[object, ...]:
        return ()

    def emitted_fills(self) -> tuple[object, ...]:
        return ()

    def emitted_signals(self) -> tuple[object, ...]:
        return ()

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def market_event_count(self) -> int:
        return self._market_event_count

    @property
    def session_event_count(self) -> int:
        return self._session_event_count

    @property
    def corporate_action_event_count(self) -> int:
        return self._corporate_action_event_count

    @property
    def started_event_seen(self) -> bool:
        return self._started_event_seen

    @property
    def finished_event_seen(self) -> bool:
        return self._finished_event_seen

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    def _count(self, kind: str, event_time: datetime | None) -> None:
        self._event_count += 1
        self._kind_counts[kind] += 1
        if event_time is not None:
            if self._last_event_time is not None and event_time < self._last_event_time:
                self._out_of_sequence_count += 1
                self._warnings.append("temporal_consistency:event_time")
                self._observe(
                    event_time,
                    kind=OBSERVATION_KIND_TEMPORAL_CONSISTENCY_WARNING,
                    message="event_time moved backward on the stream",
                    severity="warning",
                    metadata={
                        "previous_event_time": canonical_datetime(
                            self._last_event_time
                        ),
                        "event_time": canonical_datetime(event_time),
                    },
                    limited=False,
                )
            self._last_event_time = event_time
        if kind == MARKET_BAR_KIND:
            self._market_event_count += 1
        elif kind == MARKET_SESSION_KIND:
            self._session_event_count += 1
        elif kind == CORPORATE_ACTION_KIND:
            self._corporate_action_event_count += 1

    def _observe(
        self,
        event_time: datetime,
        *,
        kind: str,
        message: str,
        severity: str = "info",
        instrument_id: str | None = None,
        symbol: str | None = None,
        metadata: Mapping[str, object] | None = None,
        limited: bool = True,
    ) -> None:
        if limited:
            if (
                self._max_observations is not None
                and self._event_observation_count >= self._max_observations
            ):
                return
            self._event_observation_count += 1
        self._observations.append(
            ResearchObservation(
                observation_time=event_time,
                event_time=event_time,
                kind=kind,
                message=message,
                severity=severity,
                instrument_id=instrument_id,
                symbol=symbol,
                metadata=dict(metadata or {}),
            )
        )

    def _stamp(self) -> datetime | None:
        return self._last_event_time

    def _finish(self) -> PolicyRunOutput:
        observations = sort_observations(self._observations)
        counts: Counter[str] = Counter(item.kind for item in observations)
        summary = ResearchObservationSummary(
            observation_count=len(observations),
            event_count=self._event_count,
            market_event_count=self._market_event_count,
            session_event_count=self._session_event_count,
            corporate_action_event_count=self._corporate_action_event_count,
            warning_count=sum(1 for item in observations if item.severity == "warning"),
            error_count=sum(1 for item in observations if item.severity == "error"),
            counts_by_kind=dict(sorted(counts.items())),
        )
        draft = PolicyRunOutput(
            policy_name=self.name,
            policy_config=dict(self._config),
            observations=observations,
            summary=summary,
            policy_output_hash="",
        )
        return replace(draft, policy_output_hash=hash_policy_output(draft))


class DataQualityResearchPolicy(StreamAuditPolicy):
    """Count stream facts and emit quality notes. Not a strategy."""

    name: str = DATA_QUALITY_POLICY_NAME

    def __init__(self, *, config: Mapping[str, object] | None = None) -> None:
        parsed = _parse_data_quality_config(config)
        super().__init__(name=DATA_QUALITY_POLICY_NAME, config=parsed)
        self._emit_events = bool(parsed["emit_event_observations"])
        self._emit_summary = bool(parsed["emit_summary_observations"])
        max_obs = parsed.get("max_observations")
        self._max_observations = int(max_obs) if isinstance(max_obs, int) else None
        self._bars_by_instrument: Counter[str] = Counter()
        self._session_kind_counts: Counter[str] = Counter()
        self._open_session_count = 0
        self._holiday_session_count = 0
        self._exceptional_close_session_count = 0
        self._correction_count = 0

    def on_replay_started(self, event: ReplayStartedEvent) -> None:
        super().on_replay_started(event)
        self._maybe_event(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="replay started",
        )

    def on_market_session(self, event: MarketSessionEvent) -> None:
        super().on_market_session(event)
        self._session_kind_counts[event.session_kind] += 1
        if event.session_kind == _SESSION_OPEN or event.is_open:
            self._open_session_count += 1
        if event.session_kind == _SESSION_HOLIDAY:
            self._holiday_session_count += 1
        if event.session_kind == _SESSION_EXCEPTIONAL_CLOSE:
            self._exceptional_close_session_count += 1
        self._maybe_event(
            event.event_time,
            kind=OBSERVATION_KIND_SESSION_SEEN,
            message="market session seen",
            metadata={
                "calendar_code": event.calendar_code,
                "session_kind": event.session_kind,
                "is_open": event.is_open,
            },
        )

    def on_corporate_action(self, event: CorporateActionEvent) -> None:
        super().on_corporate_action(event)
        self._maybe_event(
            event.event_time,
            kind=OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
            message="corporate action seen",
            instrument_id=str(event.instrument_id),
            symbol=event.symbol,
            metadata={
                "action_type": event.action_type,
                "known_before_start": event.known_before_start,
            },
        )

    def on_market_bar(self, event: MarketBarEvent) -> None:
        super().on_market_bar(event)
        self._bars_by_instrument[str(event.instrument_id)] += 1
        self._maybe_event(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="market bar seen",
            instrument_id=str(event.instrument_id),
            symbol=event.symbol,
            metadata={"is_correction": event.is_correction},
        )
        if event.is_correction:
            self._correction_count += 1
            self._maybe_event(
                event.event_time,
                kind=OBSERVATION_KIND_CORRECTION_SEEN,
                message="price correction seen",
                instrument_id=str(event.instrument_id),
                symbol=event.symbol,
            )

    def on_replay_finished(self, event: ReplayFinishedEvent) -> None:
        super().on_replay_finished(event)
        self._maybe_event(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="replay finished",
        )

    def finalize(self) -> PolicyRunOutput:
        stamp = self._stamp()
        if self._emit_summary and stamp is not None:
            self._observe(
                stamp,
                kind=OBSERVATION_KIND_DATA_QUALITY_SUMMARY,
                message="stream quality counts recorded",
                metadata={
                    "event_count_by_kind": dict(sorted(self._kind_counts.items())),
                    "bars_by_instrument": dict(
                        sorted(self._bars_by_instrument.items())
                    ),
                    "session_kind_counts": dict(
                        sorted(self._session_kind_counts.items())
                    ),
                    "open_session_count": self._open_session_count,
                    "holiday_session_count": self._holiday_session_count,
                    "exceptional_close_session_count": (
                        self._exceptional_close_session_count
                    ),
                    "corporate_action_count": self._corporate_action_event_count,
                    "correction_count": self._correction_count,
                    "unknown_event_count": self._unknown_event_count,
                    "out_of_sequence_count": self._out_of_sequence_count,
                },
                limited=False,
            )
        return self._finish()

    def _maybe_event(
        self,
        event_time: datetime,
        *,
        kind: str,
        message: str,
        instrument_id: str | None = None,
        symbol: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not self._emit_events:
            return
        self._observe(
            event_time,
            kind=kind,
            message=message,
            instrument_id=instrument_id,
            symbol=symbol,
            metadata=metadata,
            limited=True,
        )


class CoverageResearchPolicy(StreamAuditPolicy):
    """Instrument and bar coverage notes. Does not compute performance."""

    name: str = COVERAGE_POLICY_NAME

    def __init__(self, *, config: Mapping[str, object] | None = None) -> None:
        parsed = _parse_coverage_config(config)
        super().__init__(name=COVERAGE_POLICY_NAME, config=parsed)
        raw_expected = parsed.get("expected_instruments")
        self._expected_instruments = (
            tuple(str(item) for item in raw_expected)
            if isinstance(raw_expected, list)
            else ()
        )
        min_bars = parsed.get("min_bars_per_instrument")
        self._min_bars = int(min_bars) if isinstance(min_bars, int) else None
        self._expected_dates = _coverage_dates(parsed)
        max_gap = parsed.get("max_gap_days")
        self._max_gap_days = int(max_gap) if isinstance(max_gap, int) else None
        self._bar_dates: dict[str, list[date]] = {}
        self._symbols: dict[str, str] = {}
        self._first_bar: dict[str, datetime] = {}
        self._last_bar: dict[str, datetime] = {}

    def on_market_bar(self, event: MarketBarEvent) -> None:
        super().on_market_bar(event)
        key = str(event.instrument_id)
        self._symbols[key] = event.symbol
        civil = event.observation_time.date()
        self._bar_dates.setdefault(key, []).append(civil)
        if key not in self._first_bar:
            self._first_bar[key] = event.observation_time
        self._last_bar[key] = event.observation_time

    def finalize(self) -> PolicyRunOutput:
        stamp = self._stamp()
        if stamp is None:
            return self._finish()
        bars_by_instrument = {
            key: len(dates) for key, dates in sorted(self._bar_dates.items())
        }
        for key, dates in sorted(self._bar_dates.items()):
            symbol = self._symbols.get(key)
            unique_dates = tuple(sorted(set(dates)))
            self._observe(
                stamp,
                kind=OBSERVATION_KIND_INSTRUMENT_SEEN,
                message="instrument had bars in the stream",
                instrument_id=key,
                symbol=symbol,
                metadata={
                    "bar_count": len(dates),
                    "distinct_bar_dates": len(unique_dates),
                    "first_bar": canonical_datetime(self._first_bar[key]),
                    "last_bar": canonical_datetime(self._last_bar[key]),
                },
                limited=False,
            )
            if self._min_bars is not None and len(dates) < self._min_bars:
                self._gap(
                    stamp,
                    message="instrument has fewer bars than the configured minimum",
                    instrument_id=key,
                    symbol=symbol,
                    metadata={
                        "bar_count": len(dates),
                        "min_bars_per_instrument": self._min_bars,
                    },
                )
            if self._max_gap_days is not None and len(unique_dates) >= 2:
                for left, right in pairwise(unique_dates):
                    span = (right - left).days
                    if span > self._max_gap_days:
                        self._gap(
                            stamp,
                            message="bar dates are farther apart than max_gap_days",
                            instrument_id=key,
                            symbol=symbol,
                            metadata={
                                "left_date": left.isoformat(),
                                "right_date": right.isoformat(),
                                "gap_days": span,
                                "max_gap_days": self._max_gap_days,
                            },
                        )
            if self._expected_dates:
                present = {item.isoformat() for item in unique_dates}
                for expected in self._expected_dates:
                    if expected not in present:
                        self._gap(
                            stamp,
                            message="expected bar date was not seen",
                            instrument_id=key,
                            symbol=symbol,
                            metadata={"expected_date": expected},
                        )
        seen_tokens = set(self._bar_dates) | set(self._symbols.values())
        for token in self._expected_instruments:
            if token not in seen_tokens:
                self._gap(
                    stamp,
                    message="expected instrument had no bars",
                    metadata={"expected_instrument": token},
                )
        self._observe(
            stamp,
            kind=OBSERVATION_KIND_COVERAGE_SUMMARY,
            message="coverage counts recorded",
            metadata={
                "instrument_count": len(self._bar_dates),
                "bars_by_instrument": bars_by_instrument,
                "expected_instrument_count": len(self._expected_instruments),
                "expected_date_count": len(self._expected_dates),
            },
            limited=False,
        )
        return self._finish()

    def _gap(
        self,
        stamp: datetime,
        *,
        message: str,
        instrument_id: str | None = None,
        symbol: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self._warnings.append("coverage_gap")
        self._observe(
            stamp,
            kind=OBSERVATION_KIND_COVERAGE_GAP,
            message=message,
            severity="warning",
            instrument_id=instrument_id,
            symbol=symbol,
            metadata=dict(metadata or {}),
            limited=False,
        )


class CorporateActionAuditPolicy(StreamAuditPolicy):
    """Count stored corporate actions. Does not adjust OHLCV."""

    name: str = CORPORATE_ACTION_AUDIT_POLICY_NAME

    def __init__(self, *, config: Mapping[str, object] | None = None) -> None:
        parsed = _parse_corporate_action_config(config)
        super().__init__(name=CORPORATE_ACTION_AUDIT_POLICY_NAME, config=parsed)
        self._emit_each = bool(parsed["emit_each_action"])
        raw_types = parsed.get("action_types")
        self._action_types = (
            frozenset(str(item) for item in raw_types)
            if isinstance(raw_types, list)
            else None
        )
        self._by_type: Counter[str] = Counter()
        self._preknown_count = 0
        self._window_count = 0
        self._matched_count = 0
        self._skipped_count = 0

    def on_corporate_action(self, event: CorporateActionEvent) -> None:
        super().on_corporate_action(event)
        allowed = self._action_types
        if allowed is not None and event.action_type not in allowed:
            self._skipped_count += 1
            return
        self._matched_count += 1
        self._by_type[event.action_type] += 1
        if event.known_before_start:
            self._preknown_count += 1
        else:
            self._window_count += 1
        if self._emit_each:
            self._observe(
                event.event_time,
                kind=OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
                message="corporate action seen",
                instrument_id=str(event.instrument_id),
                symbol=event.symbol,
                metadata={
                    "action_type": event.action_type,
                    "known_before_start": event.known_before_start,
                    "event_time": canonical_datetime(event.event_time),
                    "available_time": canonical_datetime(event.available_time),
                    "effective_time": canonical_datetime(event.effective_time),
                },
                limited=True,
            )

    def finalize(self) -> PolicyRunOutput:
        stamp = self._stamp()
        if stamp is not None:
            self._observe(
                stamp,
                kind=OBSERVATION_KIND_CORPORATE_ACTION_SUMMARY,
                message="corporate action counts recorded",
                metadata={
                    "matched_count": self._matched_count,
                    "skipped_count": self._skipped_count,
                    "preknown_count": self._preknown_count,
                    "in_window_count": self._window_count,
                    "counts_by_type": dict(sorted(self._by_type.items())),
                },
                limited=False,
            )
        return self._finish()


class CorrectionAuditPolicy(StreamAuditPolicy):
    """Count price-correction bars. Does not pick an alternate version."""

    name: str = CORRECTION_AUDIT_POLICY_NAME

    def __init__(self, *, config: Mapping[str, object] | None = None) -> None:
        parsed = _parse_correction_config(config)
        super().__init__(name=CORRECTION_AUDIT_POLICY_NAME, config=parsed)
        self._emit_each = bool(parsed["emit_each_correction"])
        self._correction_count = 0
        self._preknown_correction_count = 0
        self._reason_counts: Counter[str] = Counter()

    def on_market_bar(self, event: MarketBarEvent) -> None:
        super().on_market_bar(event)
        if not event.is_correction:
            return
        self._correction_count += 1
        if event.known_before_start:
            self._preknown_correction_count += 1
        reason = event.correction_reason or "unspecified"
        self._reason_counts[reason] += 1
        if self._emit_each:
            metadata: dict[str, object] = {
                "is_correction": True,
                "known_before_start": event.known_before_start,
                "observation_time": canonical_datetime(event.observation_time),
                "available_time": canonical_datetime(event.available_time),
            }
            if event.correction_reason:
                metadata["correction_reason"] = event.correction_reason
            self._observe(
                event.event_time,
                kind=OBSERVATION_KIND_CORRECTION_SEEN,
                message="price correction seen",
                instrument_id=str(event.instrument_id),
                symbol=event.symbol,
                metadata=metadata,
                limited=True,
            )

    def finalize(self) -> PolicyRunOutput:
        stamp = self._stamp()
        if stamp is not None:
            self._observe(
                stamp,
                kind=OBSERVATION_KIND_CORRECTION_SUMMARY,
                message="correction counts recorded",
                metadata={
                    "correction_count": self._correction_count,
                    "preknown_correction_count": self._preknown_correction_count,
                    "reason_counts": dict(sorted(self._reason_counts.items())),
                },
                limited=False,
            )
        return self._finish()


def _parse_data_quality_config(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    payload = _checked_config(value, _DATA_QUALITY_KEYS)
    emit_events = _optional_bool(payload, "emit_event_observations", default=False)
    emit_summary = _optional_bool(payload, "emit_summary_observations", default=True)
    max_observations = _optional_positive_int(payload, "max_observations")
    return {
        "emit_event_observations": emit_events,
        "emit_summary_observations": emit_summary,
        "max_observations": max_observations,
    }


def _parse_coverage_config(value: Mapping[str, object] | None) -> dict[str, object]:
    payload = _checked_config(value, _COVERAGE_KEYS)
    return {
        "expected_instruments": _optional_str_list(payload, "expected_instruments"),
        "min_bars_per_instrument": _optional_positive_int(
            payload, "min_bars_per_instrument"
        ),
        "expected_dates": _optional_str_list(payload, "expected_dates"),
        "expected_sessions": _optional_str_list(payload, "expected_sessions"),
        "max_gap_days": _optional_positive_int(payload, "max_gap_days"),
    }


def _parse_corporate_action_config(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    payload = _checked_config(value, _CORPORATE_ACTION_KEYS)
    return {
        "emit_each_action": _optional_bool(payload, "emit_each_action", default=False),
        "action_types": _optional_str_list(payload, "action_types"),
    }


def _parse_correction_config(value: Mapping[str, object] | None) -> dict[str, object]:
    payload = _checked_config(value, _CORRECTION_KEYS)
    return {
        "emit_each_correction": _optional_bool(
            payload, "emit_each_correction", default=False
        )
    }


def _coverage_dates(parsed: Mapping[str, object]) -> tuple[str, ...]:
    dates = parsed.get("expected_dates")
    sessions = parsed.get("expected_sessions")
    items: list[str] = []
    if isinstance(dates, list):
        items.extend(str(item) for item in dates)
    if isinstance(sessions, list):
        items.extend(str(item) for item in sessions)
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return tuple(unique)


def _checked_config(
    value: Mapping[str, object] | None, allowed: frozenset[str]
) -> dict[str, object]:
    payload = normalize_policy_config(value)
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BacktestError(
            "policy_config contains unknown keys",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return payload


def _optional_bool(payload: Mapping[str, object], key: str, *, default: bool) -> bool:
    if key not in payload or payload[key] is None:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise BacktestError(
            f"{key} must be a boolean",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return value


def _optional_positive_int(payload: Mapping[str, object], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(
            f"{key} must be an integer",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if value < 1:
        raise BacktestError(
            f"{key} must be >= 1",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return value


def _optional_str_list(payload: Mapping[str, object], key: str) -> list[str] | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, list):
        raise BacktestError(
            f"{key} must be a list of strings",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BacktestError(
                f"{key} must be a list of strings",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        cleaned = item.strip()
        if key in {"expected_dates", "expected_sessions"}:
            try:
                date.fromisoformat(cleaned)
            except ValueError as exc:
                raise BacktestError(
                    f"{key} entries must be ISO dates",
                    code=BacktestErrorCode.INVALID_POLICY,
                ) from exc
        items.append(cleaned)
    return items
