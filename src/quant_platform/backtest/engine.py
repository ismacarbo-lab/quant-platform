"""Dry-run backtest engine. Consumes a ready replay run; does not trade."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.policy import NoOpBacktestPolicy
from quant_platform.backtest.results import derive_backtest_id, hash_backtest_counts
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    NOOP_POLICY_NAME,
    BacktestRequest,
    BacktestResult,
    BacktestSummary,
)
from quant_platform.core.config import get_settings
from quant_platform.research.snapshots import is_sha256_digest
from quant_platform.simulation.artifacts import load_replay_events_jsonl
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.events import ReplayEvent
from quant_platform.simulation.hashing import hash_replay_events
from quant_platform.simulation.readiness import (
    evaluate_replay_run_readiness,
    resolve_replay_run_directory,
)
from quant_platform.simulation.readiness_types import ReplayRunReadinessReport
from quant_platform.simulation.run_types import EVENTS_ARTIFACT_NAME


def require_backtest_readiness(report: ReplayRunReadinessReport) -> None:
    """Fail when the replay-run readiness gate is not green."""
    if report.ready_for_backtest:
        return
    codes = sorted({item.code for item in report.issues if item.severity == "error"})
    detail = ", ".join(codes) if codes else "not ready"
    raise BacktestError(
        f"replay run is not ready for backtest ({detail})",
        code=BacktestErrorCode.NOT_READY,
    )


def execute_backtest(
    events: Sequence[ReplayEvent | str],
    request: BacktestRequest,
    *,
    stream_hash: str,
) -> BacktestResult:
    """Run NoOpBacktestPolicy over an in-memory event sequence.

    Does not place orders, simulate fills, or compute PnL.
    """
    if request.policy_name not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name must be 'noop'",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if not is_sha256_digest(stream_hash):
        raise BacktestError(
            "stream_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    policy = NoOpBacktestPolicy()
    for event in events:
        policy.observe(event)
    backtest_hash = hash_backtest_counts(
        replay_id=request.replay_id,
        stream_hash=stream_hash,
        policy_name=request.policy_name,
        event_count=policy.event_count,
        market_event_count=policy.market_event_count,
        session_event_count=policy.session_event_count,
        corporate_action_event_count=policy.corporate_action_event_count,
        started_event_seen=policy.started_event_seen,
        finished_event_seen=policy.finished_event_seen,
        warning_count=len(policy.warnings),
        error_count=len(policy.errors),
        warnings=policy.warnings,
        errors=policy.errors,
    )
    backtest_id = (
        derive_backtest_id(backtest_hash) if request.deterministic_id else uuid4()
    )
    summary = BacktestSummary(
        backtest_id=backtest_id,
        replay_id=request.replay_id,
        stream_hash=stream_hash,
        backtest_hash=backtest_hash,
        policy_name=request.policy_name,
        event_count=policy.event_count,
        market_event_count=policy.market_event_count,
        session_event_count=policy.session_event_count,
        corporate_action_event_count=policy.corporate_action_event_count,
        started_event_seen=policy.started_event_seen,
        finished_event_seen=policy.finished_event_seen,
        warning_count=len(policy.warnings),
        error_count=len(policy.errors),
        warnings=policy.warnings,
        errors=policy.errors,
    )
    return BacktestResult(
        request=request,
        summary=summary,
        orders=policy.emitted_orders(),
        fills=policy.emitted_fills(),
        signals=policy.emitted_signals(),
    )


def run_backtest_from_replay_run(
    session: Session,
    request: BacktestRequest,
    replay_base_dir: Path | str,
    *,
    output_dir: Path | str | None = None,
    created_at: datetime | None = None,
    git_commit: str | None = None,
    resolve_git: bool = True,
    research_mode: bool | None = None,
) -> BacktestResult:
    """Load a registered replay run, require readiness, and dry-run NoOp.

    Does not write orders, call the internet, or compute PnL.
    """
    mode = get_settings().is_research_mode if research_mode is None else research_mode
    if not mode:
        raise BacktestError(
            "APP_MODE must be research",
            code=BacktestErrorCode.APP_MODE_NOT_RESEARCH,
        )
    if request.policy_name != NOOP_POLICY_NAME:
        raise BacktestError(
            "only NoOpBacktestPolicy ('noop') is implemented",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    report = evaluate_replay_run_readiness(
        session, request.replay_id, replay_base_dir, research_mode=mode
    )
    require_backtest_readiness(report)
    run_dir = resolve_replay_run_directory(replay_base_dir, request.replay_id)
    if run_dir is None:
        raise BacktestError(
            "replay run directory could not be resolved",
            code=BacktestErrorCode.NOT_READY,
        )
    events_path = run_dir / EVENTS_ARTIFACT_NAME
    try:
        events = load_replay_events_jsonl(events_path)
        recomputed = hash_replay_events(events)
    except SimulationError as exc:
        raise BacktestError(
            str(exc),
            code=BacktestErrorCode.BROKEN_RUN,
        ) from exc
    expected = report.stream_hash
    if expected is None or recomputed != expected:
        raise BacktestError(
            "recomputed stream_hash does not match the registered replay run",
            code=BacktestErrorCode.BROKEN_RUN,
        )
    result = execute_backtest(events, request, stream_hash=recomputed)
    if output_dir is None:
        return result
    return write_backtest_artifacts(
        result,
        output_dir,
        created_at=created_at,
        git_commit=git_commit,
        resolve_git=resolve_git,
    )
