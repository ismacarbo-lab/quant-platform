"""Deterministic backtest hashes. No wall-clock, paths, or random UUIDs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from uuid import UUID

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.types import (
    BACKTEST_HASH_FORMAT_VERSION,
    BACKTEST_HASH_KIND,
    BacktestResult,
    BacktestSummary,
)
from quant_platform.research.snapshots import is_sha256_digest, sha256_canonical


def hash_backtest_result(result: BacktestResult) -> str:
    """SHA-256 of counts, hashes, policy, and warning/error codes."""
    return hash_backtest_summary(result.summary)


def hash_backtest_summary(summary: BacktestSummary) -> str:
    return _hash_backtest_payload(
        replay_id=summary.replay_id,
        stream_hash=summary.stream_hash,
        policy_name=summary.policy_name,
        event_count=summary.event_count,
        market_event_count=summary.market_event_count,
        session_event_count=summary.session_event_count,
        corporate_action_event_count=summary.corporate_action_event_count,
        started_event_seen=summary.started_event_seen,
        finished_event_seen=summary.finished_event_seen,
        warning_count=summary.warning_count,
        error_count=summary.error_count,
        warnings=summary.warnings,
        errors=summary.errors,
    )


def hash_backtest_counts(
    *,
    replay_id: str,
    stream_hash: str,
    policy_name: str,
    event_count: int,
    market_event_count: int,
    session_event_count: int,
    corporate_action_event_count: int,
    started_event_seen: bool,
    finished_event_seen: bool,
    warning_count: int,
    error_count: int,
    warnings: tuple[str, ...],
    errors: tuple[str, ...],
) -> str:
    return _hash_backtest_payload(
        replay_id=replay_id,
        stream_hash=stream_hash,
        policy_name=policy_name,
        event_count=event_count,
        market_event_count=market_event_count,
        session_event_count=session_event_count,
        corporate_action_event_count=corporate_action_event_count,
        started_event_seen=started_event_seen,
        finished_event_seen=finished_event_seen,
        warning_count=warning_count,
        error_count=error_count,
        warnings=warnings,
        errors=errors,
    )


def hash_backtest_mapping(summary: Mapping[str, object]) -> str:
    """Recompute ``backtest_hash`` from a summary.json object."""
    warnings = _string_tuple(summary.get("warnings"))
    errors = _string_tuple(summary.get("errors"))
    return hash_backtest_counts(
        replay_id=_require_str(summary.get("replay_id"), field="replay_id"),
        stream_hash=_require_str(summary.get("stream_hash"), field="stream_hash"),
        policy_name=_require_str(summary.get("policy_name"), field="policy_name"),
        event_count=_require_int(summary.get("event_count"), field="event_count"),
        market_event_count=_require_int(
            summary.get("market_event_count"), field="market_event_count"
        ),
        session_event_count=_require_int(
            summary.get("session_event_count"), field="session_event_count"
        ),
        corporate_action_event_count=_require_int(
            summary.get("corporate_action_event_count"),
            field="corporate_action_event_count",
        ),
        started_event_seen=_require_bool(
            summary.get("started_event_seen"), field="started_event_seen"
        ),
        finished_event_seen=_require_bool(
            summary.get("finished_event_seen"), field="finished_event_seen"
        ),
        warning_count=_require_int(summary.get("warning_count"), field="warning_count"),
        error_count=_require_int(summary.get("error_count"), field="error_count"),
        warnings=warnings,
        errors=errors,
    )


def derive_backtest_id(backtest_hash: str) -> UUID:
    """Stable UUID from ``backtest_hash``. Default runs still use UUID4."""
    if not is_sha256_digest(backtest_hash):
        raise BacktestError(
            "backtest_hash must be sha256:<64 hex>",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    digest = hashlib.sha256(backtest_hash.encode("utf-8")).digest()
    return UUID(bytes=digest[:16])


def _hash_backtest_payload(
    *,
    replay_id: str,
    stream_hash: str,
    policy_name: str,
    event_count: int,
    market_event_count: int,
    session_event_count: int,
    corporate_action_event_count: int,
    started_event_seen: bool,
    finished_event_seen: bool,
    warning_count: int,
    error_count: int,
    warnings: tuple[str, ...],
    errors: tuple[str, ...],
) -> str:
    payload = {
        "kind": BACKTEST_HASH_KIND,
        "version": BACKTEST_HASH_FORMAT_VERSION,
        "replay_id": replay_id,
        "stream_hash": stream_hash,
        "policy_name": policy_name,
        "event_count": event_count,
        "market_event_count": market_event_count,
        "session_event_count": session_event_count,
        "corporate_action_event_count": corporate_action_event_count,
        "started_event_seen": started_event_seen,
        "finished_event_seen": finished_event_seen,
        "warning_count": warning_count,
        "error_count": error_count,
        "warnings": list(warnings),
        "errors": list(errors),
    }
    return sha256_canonical(payload)


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BacktestError(
            f"summary.{field} must be a non-empty string",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value.strip()


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(
            f"summary.{field} must be an integer",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise BacktestError(
            f"summary.{field} must be a boolean",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BacktestError(
            "summary warning/error lists must be strings",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return tuple(value)
