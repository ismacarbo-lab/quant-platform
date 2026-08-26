"""No-op event counter. This is not a strategy and emits no orders."""

from __future__ import annotations

from quant_platform.backtest.types import NOOP_POLICY_NAME
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    EVENT_PRIORITY,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    ReplayEvent,
)

_ALLOWED_KINDS = frozenset(EVENT_PRIORITY)


class NoOpBacktestPolicy:
    """Count replay events. Not a strategy: no signals, orders, or positions."""

    name: str = NOOP_POLICY_NAME

    def __init__(self) -> None:
        self._event_count = 0
        self._market_event_count = 0
        self._session_event_count = 0
        self._corporate_action_event_count = 0
        self._started_event_seen = False
        self._finished_event_seen = False
        self._warnings: list[str] = []
        self._errors: list[str] = []

    def observe(self, event: ReplayEvent | str) -> None:
        kind = event if isinstance(event, str) else event.kind
        self._event_count += 1
        if kind == MARKET_BAR_KIND:
            self._market_event_count += 1
            return
        if kind == MARKET_SESSION_KIND:
            self._session_event_count += 1
            return
        if kind == CORPORATE_ACTION_KIND:
            self._corporate_action_event_count += 1
            return
        if kind == REPLAY_STARTED_KIND:
            self._started_event_seen = True
            return
        if kind == REPLAY_FINISHED_KIND:
            self._finished_event_seen = True
            return
        if kind not in _ALLOWED_KINDS:
            self._warnings.append(f"unknown_event:{kind}")

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


EventCountingBacktestPolicy = NoOpBacktestPolicy
