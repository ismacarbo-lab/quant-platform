"""Research dataset replay. Not backtesting, strategies, or trading."""

from quant_platform.simulation.audit import (
    ReplayAuditCode,
    ReplayAuditIssue,
    ReplayAuditReport,
    ReplayAuditSeverity,
    audit_replay,
)
from quant_platform.simulation.clock import SimulationClock
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.event_fixtures import (
    ReplayEventFixture,
    load_replay_events_json,
    replay_event_fixtures_dir,
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
    apply_start_boundary,
    corporate_action_event_from_row,
    is_pre_known_event,
    market_bar_event_from_row,
    replay_boundary_group,
    replay_event_sort_key,
)
from quant_platform.simulation.hashing import (
    derive_replay_id,
    hash_replay_events,
    hash_replay_request,
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
    "CORPORATE_ACTION_KIND",
    "EVENT_PRIORITY",
    "MARKET_BAR_KIND",
    "MARKET_SESSION_KIND",
    "REPLAY_FINISHED_KIND",
    "REPLAY_STARTED_KIND",
    "SOURCE_DATABASE",
    "SOURCE_SNAPSHOT",
    "CorporateActionEvent",
    "DailyBarReplay",
    "MarketBarEvent",
    "MarketSessionEvent",
    "ReplayAuditCode",
    "ReplayAuditIssue",
    "ReplayAuditReport",
    "ReplayAuditSeverity",
    "ReplayEvent",
    "ReplayEventFixture",
    "ReplayFinishedEvent",
    "ReplayStartedEvent",
    "ReplaySummary",
    "SimulationClock",
    "SimulationError",
    "SimulationErrorCode",
    "apply_start_boundary",
    "audit_replay",
    "corporate_action_event_from_row",
    "create_daily_bar_replay",
    "derive_replay_id",
    "hash_replay_events",
    "hash_replay_request",
    "is_pre_known_event",
    "load_replay_events_json",
    "market_bar_event_from_row",
    "replay_boundary_group",
    "replay_daily_bars_dataset",
    "replay_daily_bars_snapshot",
    "replay_event_fixtures_dir",
    "replay_event_sort_key",
]
