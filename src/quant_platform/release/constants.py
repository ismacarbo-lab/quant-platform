"""Research release-candidate constants. Not a trading or AI runtime."""

from __future__ import annotations

EXPECTED_ALEMBIC_HEAD = "0009_backtest_experiments"

RELEASE_STATUS_KIND = "research_release_status"
RELEASE_STATUS_FORMAT_VERSION = 2
RELEASE_STATUS_HASH_KIND = "research_release_status"
RELEASE_STATUS_HASH_FORMAT_VERSION = 2

FREEZE_DOC_PATHS: tuple[str, ...] = (
    "docs/adr/0003-research-mode-freeze.md",
    "docs/release/CAPABILITY_MATRIX.md",
    "docs/release/COMMANDS.md",
    "docs/release/FINAL_RESEARCH_CHECKLIST.md",
    "docs/release/MINIMAL_REPRODUCIBLE_EXAMPLE.md",
    "docs/release/RESEARCH_HANDOFF.md",
    "docs/release/RISK_REGISTER.md",
)
EVIDENCE_BUNDLE_DOC_PATH = "docs/release/RESEARCH_EVIDENCE_BUNDLE.md"
EVIDENCE_BUNDLE_MODULE_PATH = "src/quant_platform/release/evidence_bundle.py"

ENABLED_CAPABILITIES: tuple[str, ...] = (
    "research_mode",
    "postgresql",
    "alembic",
    "local_csv_ingestion",
    "instrument_master",
    "calendars",
    "corporate_action_store",
    "dataset_api",
    "dataset_quality_reports",
    "dataset_snapshots",
    "dataset_catalog",
    "replay_engine",
    "replay_audit",
    "replay_run_registry",
    "backtest_readiness",
    "dry_run_backtest",
    "research_policies",
    "policy_output_integrity",
    "backtest_experiments",
    "policy_regression_matrix",
    "research_evidence_bundle",
    "corporate_action_normalization",
    "health_endpoint",
)

DISABLED_CAPABILITIES: tuple[str, ...] = (
    "paper_trading",
    "live_trading",
    "brokers",
    "order_execution",
    "portfolio",
    "positions",
    "pnl",
    "returns",
    "signals",
    "strategies",
    "fills",
    "trades",
    "ai_runtime",
    "openai",
    "anthropic",
    "langchain",
    "rag",
    "external_market_data_vendors",
    "sqlite_fallback",
    "cloud_object_storage",
)

FORBIDDEN_RUNTIME_PACKAGES: tuple[str, ...] = (
    "broker",
    "brokers",
    "execution",
    "fills",
    "live",
    "llm",
    "orders",
    "paper",
    "portfolio",
    "positions",
    "rag",
    "signal",
    "signals",
    "strategies",
    "strategy",
    "trades",
    "trading",
)

FORBIDDEN_DEPENDENCY_NAMES = frozenset(
    {
        "alpaca",
        "alpaca-py",
        "anthropic",
        "ccxt",
        "chromadb",
        "cursor",
        "cursor-sdk",
        "cursor_sdk",
        "finnhub",
        "ib-insync",
        "ib_insync",
        "ibapi",
        "langchain",
        "langgraph",
        "llama-index",
        "llama_index",
        "openai",
        "polygon",
        "tiingo",
        "transformers",
        "yfinance",
    }
)

EXPECTED_PUBLIC_TABLES = frozenset(
    {
        "alembic_version",
        "backtest_experiments",
        "backtest_runs",
        "corporate_actions",
        "daily_bars",
        "data_sources",
        "dataset_snapshots",
        "exchanges",
        "ingestion_errors",
        "ingestion_runs",
        "instrument_identifiers",
        "instruments",
        "market_calendars",
        "market_sessions",
        "raw_ingestion_records",
        "simulation_replay_runs",
    }
)

SMOKE_IMPORT_MODULES: tuple[str, ...] = (
    "quant_platform",
    "quant_platform.api.app",
    "quant_platform.backtest.policy_registry",
    "quant_platform.core.config",
    "quant_platform.release.evidence_bundle",
    "quant_platform.release.status",
    "quant_platform.research.normalization",
    "quant_platform.storage.database",
)
