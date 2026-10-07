"""Backtest results and the run action."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from quant_platform.api.deps import (
    get_db,
    get_jobs,
    get_session_factory,
    get_settings_dep,
)
from quant_platform.api.jobs import JobRegistry
from quant_platform.backtesting.runner import (
    get_strategy_backtest,
    latest_backtest_per_strategy,
    list_strategy_backtests,
    record_detail,
    record_summary,
)
from quant_platform.core.config import Settings
from quant_platform.marketdata.universe import DEFAULT_HISTORY_START
from quant_platform.strategies import STRATEGY_SPECS, StrategyError, strategy_spec

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


class BacktestRunRequest(BaseModel):
    strategies: list[str] | None = Field(
        default=None, description="Strategy names; default runs all."
    )
    params: dict[str, Any] | None = None
    start: date = DEFAULT_HISTORY_START
    end: date | None = None
    rebalance: str = "monthly"
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    initial_cash: float = Field(default=100_000.0, gt=0)
    walk_forward: bool = True
    min_is_years: int = Field(default=5, ge=2, le=15)
    include_crypto: bool = False


@router.get("")
def list_backtests(
    db: Annotated[Session, Depends(get_db)],
    strategy: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    rows = list_strategy_backtests(db, limit=limit, strategy_name=strategy)
    return {"backtests": [record_summary(row) for row in rows]}


@router.get("/ranking")
def ranking(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    rows = latest_backtest_per_strategy(db)
    summaries = [record_summary(row) for row in rows]

    def sort_key(item: dict[str, object]) -> float:
        metrics = item.get("metrics")
        if isinstance(metrics, dict):
            sharpe = metrics.get("sharpe")
            if isinstance(sharpe, int | float):
                return -float(sharpe)
        return float("inf")

    summaries.sort(key=sort_key)
    return {"ranking": summaries}


@router.get("/{record_id}")
def backtest_detail(
    record_id: UUID, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    record = get_strategy_backtest(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    return record_detail(record)


@router.post("/run", status_code=202)
def run_backtests(
    body: BacktestRunRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> dict[str, object]:
    names = body.strategies or [spec.name for spec in STRATEGY_SPECS]
    for name in names:
        try:
            strategy_spec(name)
        except StrategyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if body.params is not None and len(names) != 1:
        raise HTTPException(
            status_code=400, detail="params require exactly one strategy"
        )
    if jobs.running("backtest"):
        raise HTTPException(status_code=409, detail="a backtest job is already running")

    def runner() -> dict[str, Any]:
        from quant_platform.backtesting.data import load_price_panel
        from quant_platform.backtesting.engine import BacktestConfig
        from quant_platform.backtesting.runner import run_strategy_backtest_on_panel
        from quant_platform.backtesting.walk_forward import WalkForwardConfig
        from quant_platform.marketdata.universe import (
            resolve_universe,
            universe_symbols,
        )
        from quant_platform.research.snapshots import get_git_commit

        universe = resolve_universe(None, include_optional=body.include_crypto)
        config = BacktestConfig(
            rebalance=body.rebalance,
            commission_bps=body.commission_bps,
            slippage_bps=body.slippage_bps,
            initial_cash=body.initial_cash,
            universe=tuple(universe),
        )
        session = factory()
        try:
            panel = load_price_panel(
                session,
                source_name=settings.market_data_source_name,
                symbols=universe_symbols(universe),
                start=body.start,
                end=body.end or datetime.now(tz=UTC).date(),
            )
            git_commit = get_git_commit()
            results = []
            for name in names:
                outcome = run_strategy_backtest_on_panel(
                    session,
                    panel,
                    strategy_name=name,
                    params=body.params,
                    config=config,
                    walk_forward=body.walk_forward,
                    wf_config=WalkForwardConfig(min_is_years=body.min_is_years),
                    git_commit=git_commit,
                )
                session.commit()
                results.append(outcome.summary())
            return {"results": results, "panel_sessions": panel.session_count}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    job = jobs.submit("backtest", runner, params=body.model_dump(mode="json"))
    return job.as_mapping(include_result=False)
