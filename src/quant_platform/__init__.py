"""Quantitative research platform — research-only foundation.

This package does not implement strategies, vendor market-data clients,
brokers, or order execution. Phase 4.0-4.1 add a dry-run backtest engine
with NoOp counts, hashes, and artifact integrity. Phase 4.2 adds a
research-policy interface (observations and counters only - still no
orders, fills, portfolio, or PnL). Phase 4.3 adds observation reports
and policy-output integrity (still no signals or orders).
"""

__version__ = "0.1.0"
