"""Research policy protocol. Not a strategy, signal, or execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import PolicyRunOutput
from quant_platform.simulation.events import (
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)


@runtime_checkable
class EventObserver(Protocol):
    """Consumes replay events. Does not emit investment decisions."""

    def observe(self, event: ReplayEvent | str) -> None: ...


@runtime_checkable
class ResearchPolicy(Protocol):
    """Controlled research observer used by the dry-run backtest engine.

    Implementations may count events and emit ``ResearchObservation`` values.
    They must not emit buy/sell/hold recommendations, signals, orders,
    positions, or PnL.
    """

    name: str

    def on_replay_started(self, event: ReplayStartedEvent) -> None: ...

    def on_market_session(self, event: MarketSessionEvent) -> None: ...

    def on_corporate_action(self, event: CorporateActionEvent) -> None: ...

    def on_market_bar(self, event: MarketBarEvent) -> None: ...

    def on_replay_finished(self, event: ReplayFinishedEvent) -> None: ...

    def finalize(self) -> PolicyRunOutput: ...


@runtime_checkable
class CountingResearchPolicy(Protocol):
    """Research policy that exposes stream counters. Not a trading API."""

    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    started_event_seen: bool
    finished_event_seen: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def emitted_orders(self) -> tuple[object, ...]: ...

    def emitted_fills(self) -> tuple[object, ...]: ...

    def emitted_signals(self) -> tuple[object, ...]: ...


@dataclass(frozen=True, slots=True)
class ResearchPolicyStreamMetrics:
    """Event counts collected by a research policy. Not PnL or holdings."""

    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    started_event_seen: bool
    finished_event_seen: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    orders: tuple[object, ...]
    fills: tuple[object, ...]
    signals: tuple[object, ...]


def research_policy_stream_metrics(policy: object) -> ResearchPolicyStreamMetrics:
    """Read stream counters from a research policy. Rejects trading payloads."""
    if not isinstance(policy, CountingResearchPolicy):
        raise BacktestError(
            "registered research policy must count events without trading",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    orders = tuple(policy.emitted_orders())
    fills = tuple(policy.emitted_fills())
    signals = tuple(policy.emitted_signals())
    if orders or fills or signals:
        raise BacktestError(
            "research policy must not emit orders, fills, or signals",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return ResearchPolicyStreamMetrics(
        event_count=int(policy.event_count),
        market_event_count=int(policy.market_event_count),
        session_event_count=int(policy.session_event_count),
        corporate_action_event_count=int(policy.corporate_action_event_count),
        started_event_seen=bool(policy.started_event_seen),
        finished_event_seen=bool(policy.finished_event_seen),
        warnings=tuple(policy.warnings),
        errors=tuple(policy.errors),
        orders=orders,
        fills=fills,
        signals=signals,
    )


def apply_research_event(policy: ResearchPolicy, event: ReplayEvent | str) -> None:
    """Dispatch a replay event to a research policy. Not an order router."""
    if isinstance(event, ReplayStartedEvent):
        policy.on_replay_started(event)
        return
    if isinstance(event, MarketSessionEvent):
        policy.on_market_session(event)
        return
    if isinstance(event, CorporateActionEvent):
        policy.on_corporate_action(event)
        return
    if isinstance(event, MarketBarEvent):
        policy.on_market_bar(event)
        return
    if isinstance(event, ReplayFinishedEvent):
        policy.on_replay_finished(event)
        return
    observer = getattr(policy, "observe", None)
    if callable(observer):
        observer(event)
        return
    raise TypeError("research policy cannot observe unknown event payload")
