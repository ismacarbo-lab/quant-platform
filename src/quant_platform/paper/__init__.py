"""Simulated paper trading with fictional cash (ADR 0005).

Nothing in this package talks to a real broker. ``BrokerAdapter`` is the
seam where one could be plugged in later; only ``SimulatedBroker`` exists.
"""

from quant_platform.paper.broker import (
    BrokerAdapter,
    ExecutionPrices,
    FillResult,
    OrderIntent,
    SimulatedBroker,
)
from quant_platform.paper.engine import (
    PaperAccountRunReport,
    PaperEngine,
    PaperEngineError,
    PaperRunReport,
)
from quant_platform.paper.models import (
    PaperAccount,
    PaperEquitySnapshot,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperRun,
)

__all__ = [
    "BrokerAdapter",
    "ExecutionPrices",
    "FillResult",
    "OrderIntent",
    "PaperAccount",
    "PaperAccountRunReport",
    "PaperEngine",
    "PaperEngineError",
    "PaperEquitySnapshot",
    "PaperFill",
    "PaperOrder",
    "PaperPosition",
    "PaperRun",
    "PaperRunReport",
    "SimulatedBroker",
]
