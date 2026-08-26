"""Research dataset replay. Not backtesting, strategies, or trading."""

from quant_platform.simulation.clock import SimulationClock
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    MARKET_BAR_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    MarketBarEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    market_bar_event_from_row,
)
from quant_platform.simulation.replay import (
    DailyBarReplay,
    create_daily_bar_replay,
    replay_daily_bars_dataset,
    replay_daily_bars_snapshot,
)
from quant_platform.simulation.summary import (
    SOURCE_DATABASE,
    SOURCE_SNAPSHOT,
    ReplaySummary,
)

__all__ = [
    "MARKET_BAR_KIND",
    "REPLAY_FINISHED_KIND",
    "REPLAY_STARTED_KIND",
    "SOURCE_DATABASE",
    "SOURCE_SNAPSHOT",
    "DailyBarReplay",
    "MarketBarEvent",
    "ReplayEvent",
    "ReplayFinishedEvent",
    "ReplayStartedEvent",
    "ReplaySummary",
    "SimulationClock",
    "SimulationError",
    "SimulationErrorCode",
    "create_daily_bar_replay",
    "market_bar_event_from_row",
    "replay_daily_bars_dataset",
    "replay_daily_bars_snapshot",
]
