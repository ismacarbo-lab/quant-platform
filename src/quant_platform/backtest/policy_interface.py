"""Research policy protocol. Not a strategy, signal, or execution engine."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
