"""Quantitative research platform — research-only foundation.

This package does not implement strategies, vendor market-data clients,
brokers, or order execution. Phase 4.0 adds a dry-run backtest engine
(`quant_platform.backtest`) that consumes a ready replay run with
NoOpBacktestPolicy. Phase 4.1 verifies local backtest artifacts,
compares runs, and gates whether a NoOp result is usable evidence —
still no orders, fills, portfolio, or PnL.
"""

__version__ = "0.1.0"
