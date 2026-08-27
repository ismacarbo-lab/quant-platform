"""Quantitative research platform — research-only foundation.

This package does not implement strategies, vendor market-data clients,
brokers, or order execution. Phase 4.0-4.5 add a dry-run backtest engine,
research policies, experiment registry, usability gates, and hashes.
Phase 5.0 adds data-quality research policies (coverage, corporate-action
and correction audit) without signals, orders, fills, portfolio, or PnL.
Phase 5.1 adds a ResearchPolicy regression matrix with golden fixtures.
Phase 5.2 hardens a research-mode release candidate (status, guardrails,
and local release checks) still without trading or AI runtime.
Phase 5.3 adds an end-to-end research evidence bundle (local fixtures
through snapshot, replay, dry-run, experiment, and release status).
Phase 5.4 freezes research mode (handoff, checklists, capability and
risk matrices) still without trading or AI runtime.
"""

__version__ = "0.1.0"
