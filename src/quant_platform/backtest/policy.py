"""Event-counting research policy. This is not a strategy and emits no orders."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from quant_platform.backtest.observations import (
    OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
    OBSERVATION_KIND_CORRECTION_SEEN,
    OBSERVATION_KIND_EVENT_SEEN,
    OBSERVATION_KIND_MISSING_EXPECTED_EVENT,
    OBSERVATION_KIND_POLICY_NOTE,
    OBSERVATION_KIND_SESSION_SEEN,
    OBSERVATION_KIND_UNKNOWN_EVENT,
    PolicyRunOutput,
    ResearchObservation,
    ResearchObservationSummary,
    hash_policy_output,
    normalize_policy_config,
    sort_observations,
)
from quant_platform.backtest.types import (
    EVENT_COUNTING_POLICY_NAME,
    NOOP_POLICY_NAME,
)
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


class EventCountingResearchPolicy:
    """Count replay events and optionally emit descriptive observations.

    Not a strategy: no signals, orders, positions, or PnL.
    """

    name: str = NOOP_POLICY_NAME

    def __init__(
        self,
        *,
        name: str = NOOP_POLICY_NAME,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self.name = name.strip() or NOOP_POLICY_NAME
        self._config = normalize_policy_config(config)
        emit = self._config.get("emit_observations")
        self._emit_observations = (
            self.name == EVENT_COUNTING_POLICY_NAME or emit is True
        )
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

    def on_replay_started(self, event: ReplayStartedEvent) -> None:
        self._count(REPLAY_STARTED_KIND, event.event_time)
        self._started_event_seen = True
        self._maybe_observe(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="replay started",
        )

    def on_market_session(self, event: MarketSessionEvent) -> None:
        self._count(MARKET_SESSION_KIND, event.event_time)
        self._maybe_observe(
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
        self._count(CORPORATE_ACTION_KIND, event.event_time)
        self._maybe_observe(
            event.event_time,
            kind=OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
            message="corporate action seen",
            instrument_id=str(event.instrument_id),
            symbol=event.symbol,
            metadata={"action_type": event.action_type},
        )

    def on_market_bar(self, event: MarketBarEvent) -> None:
        self._count(MARKET_BAR_KIND, event.event_time)
        self._maybe_observe(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="market bar seen",
            instrument_id=str(event.instrument_id),
            symbol=event.symbol,
            metadata={"is_correction": event.is_correction},
        )
        if event.is_correction:
            self._maybe_observe(
                event.event_time,
                kind=OBSERVATION_KIND_CORRECTION_SEEN,
                message="price correction seen",
                instrument_id=str(event.instrument_id),
                symbol=event.symbol,
            )

    def on_replay_finished(self, event: ReplayFinishedEvent) -> None:
        self._count(REPLAY_FINISHED_KIND, event.event_time)
        self._finished_event_seen = True
        self._maybe_observe(
            event.event_time,
            kind=OBSERVATION_KIND_EVENT_SEEN,
            message="replay finished",
        )

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
            self._warnings.append(f"unknown_event:{kind}")
            stamp = self._last_event_time
            if stamp is not None:
                self._maybe_observe(
                    stamp,
                    kind=OBSERVATION_KIND_UNKNOWN_EVENT,
                    message="unrecognized replay event kind",
                    severity="warning",
                )

    def finalize(self) -> PolicyRunOutput:
        stamp = self._last_event_time
        if self._emit_observations and stamp is not None:
            if not self._started_event_seen:
                self._warnings.append("missing_expected_event:replay_started")
                self._observations.append(
                    ResearchObservation(
                        observation_time=stamp,
                        event_time=stamp,
                        kind=OBSERVATION_KIND_MISSING_EXPECTED_EVENT,
                        message="replay started event was not seen",
                        severity="warning",
                    )
                )
            if not self._finished_event_seen:
                self._warnings.append("missing_expected_event:replay_finished")
                self._observations.append(
                    ResearchObservation(
                        observation_time=stamp,
                        event_time=stamp,
                        kind=OBSERVATION_KIND_MISSING_EXPECTED_EVENT,
                        message="replay finished event was not seen",
                        severity="warning",
                    )
                )
            self._observations.append(
                ResearchObservation(
                    observation_time=stamp,
                    event_time=stamp,
                    kind=OBSERVATION_KIND_POLICY_NOTE,
                    message="event counts recorded",
                    severity="info",
                    metadata={
                        "event_count": self._event_count,
                        "market_event_count": self._market_event_count,
                    },
                )
            )
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

    def emitted_orders(self) -> tuple[object, ...]:
        return ()

    def emitted_fills(self) -> tuple[object, ...]:
        return ()

    def emitted_signals(self) -> tuple[object, ...]:
        return ()

    @property
    def orders(self) -> tuple[object, ...]:
        return ()

    @property
    def fills(self) -> tuple[object, ...]:
        return ()

    @property
    def signals(self) -> tuple[object, ...]:
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
        if event_time is not None:
            self._last_event_time = event_time
        if kind == MARKET_BAR_KIND:
            self._market_event_count += 1
        elif kind == MARKET_SESSION_KIND:
            self._session_event_count += 1
        elif kind == CORPORATE_ACTION_KIND:
            self._corporate_action_event_count += 1

    def _maybe_observe(
        self,
        event_time: datetime,
        *,
        kind: str,
        message: str,
        severity: str = "info",
        instrument_id: str | None = None,
        symbol: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not self._emit_observations:
            return
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


NoOpBacktestPolicy = EventCountingResearchPolicy
EventCountingBacktestPolicy = EventCountingResearchPolicy
