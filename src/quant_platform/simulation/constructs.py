"""Detect trading constructs that must not exist before backtesting.

This is a research guardrail, not a strategy or broker adapter.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from quant_platform.simulation.events import EVENT_PRIORITY
from quant_platform.simulation.readiness_types import (
    ReplayRunReadinessCode,
    TradingConstructFinding,
)

FORBIDDEN_PACKAGE_NAMES = frozenset(
    {
        "backtesting",
        "broker",
        "brokers",
        "execution",
        "orders",
        "portfolio",
        "signals",
        "strategies",
        "strategy",
    }
)
FORBIDDEN_TABLE_NAMES = frozenset(
    {
        "fills",
        "orders",
        "positions",
        "signals",
        "strategies",
        "trades",
    }
)
FORBIDDEN_EVENT_KIND_FRAGMENTS = (
    "fill",
    "order",
    "portfolio",
    "position",
    "signal",
    "trade",
)
ALLOWED_EVENT_KINDS = frozenset(EVENT_PRIORITY)


def detect_trading_constructs(
    *,
    package_root: Path | str | None = None,
    table_names: Iterable[str] | None = None,
    event_kinds: Iterable[str] | None = None,
    scan_packages: bool = True,
    scan_tables: bool = True,
) -> tuple[TradingConstructFinding, ...]:
    """Return findings for forbidden packages, tables, or event kinds.

    Does not scan markdown. Package scan is direct children of
    ``quant_platform`` only.
    """
    findings: list[TradingConstructFinding] = []
    if scan_packages:
        root = (
            Path(package_root) if package_root is not None else _quant_platform_root()
        )
        findings.extend(_package_findings(root))
    if scan_tables:
        names = (
            tuple(table_names) if table_names is not None else _metadata_table_names()
        )
        findings.extend(_table_findings(names))
    if event_kinds is not None:
        findings.extend(_event_kind_findings(event_kinds))
    return tuple(findings)


def event_kinds_from_counts(counts: object) -> tuple[str, ...]:
    """Extract event kind names from ``counts_by_kind`` / ``event_counts_by_type``."""
    if not isinstance(counts, dict):
        return ()
    kinds: list[str] = []
    for key in counts:
        if isinstance(key, str) and key.strip():
            kinds.append(key.strip())
    return tuple(sorted(kinds))


def _quant_platform_root() -> Path:
    import quant_platform

    return Path(quant_platform.__file__).resolve().parent


def _metadata_table_names() -> tuple[str, ...]:
    from quant_platform.data import models as _models  # noqa: F401
    from quant_platform.storage.database import Base

    return tuple(sorted(Base.metadata.tables))


def _package_findings(root: Path) -> list[TradingConstructFinding]:
    findings: list[TradingConstructFinding] = []
    if not root.is_dir():
        return findings
    for name in sorted(FORBIDDEN_PACKAGE_NAMES):
        as_dir = root / name
        as_module = root / f"{name}.py"
        if as_dir.is_dir() or as_module.is_file():
            findings.append(
                TradingConstructFinding(
                    kind="package",
                    name=name,
                    code=ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED.value,
                    message=f"forbidden package {name!r} exists under quant_platform",
                )
            )
    return findings


def _table_findings(names: Sequence[str]) -> list[TradingConstructFinding]:
    findings: list[TradingConstructFinding] = []
    present = set(names)
    for name in sorted(FORBIDDEN_TABLE_NAMES):
        if name in present:
            findings.append(
                TradingConstructFinding(
                    kind="table",
                    name=name,
                    code=ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED.value,
                    message=f"forbidden trading table {name!r} is registered",
                )
            )
    return findings


def _event_kind_findings(kinds: Iterable[str]) -> list[TradingConstructFinding]:
    findings: list[TradingConstructFinding] = []
    seen: set[str] = set()
    for raw in kinds:
        kind = raw.strip()
        if not kind or kind in seen:
            continue
        seen.add(kind)
        lowered = kind.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_EVENT_KIND_FRAGMENTS):
            findings.append(
                TradingConstructFinding(
                    kind="event",
                    name=kind,
                    code=ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED.value,
                    message=f"forbidden trading event kind {kind!r}",
                )
            )
        elif kind not in ALLOWED_EVENT_KINDS:
            findings.append(
                TradingConstructFinding(
                    kind="event",
                    name=kind,
                    code=ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED.value,
                    message=f"unknown replay event kind {kind!r}",
                )
            )
    return findings
