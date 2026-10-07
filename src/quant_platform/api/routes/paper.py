"""Paper-trading endpoints (fictional money)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

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
from quant_platform.core.config import Settings
from quant_platform.paper.engine import PaperEngine, PaperEngineError
from quant_platform.paper.queries import (
    account_summary,
    equity_curve,
    fills,
    orders,
    positions,
    runs,
)
from quant_platform.strategies import StrategyError

router = APIRouter(prefix="/api/paper", tags=["paper"])


class PaperRunRequest(BaseModel):
    fetch: bool = Field(default=False, description="Download latest data first.")
    replay_from: date | None = None
    accounts: list[str] | None = None


class CreateAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    strategy_name: str
    params: dict[str, Any] | None = None
    initial_cash: Decimal | None = Field(default=None, gt=0)
    rebalance: str | None = None
    notes: str | None = None


def _require_paper(settings: Settings) -> None:
    if not settings.is_paper_mode:
        raise HTTPException(
            status_code=409,
            detail="APP_MODE must be paper to change paper accounts (fictional money)",
        )


@router.get("/accounts")
def list_accounts(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    engine = PaperEngine(db, settings, require_paper_mode=False)
    return {
        "paper_enabled": settings.is_paper_mode,
        "accounts": [account_summary(db, item) for item in engine.list_accounts()],
    }


@router.get("/accounts/{name}")
def account_detail(
    name: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    engine = PaperEngine(db, settings, require_paper_mode=False)
    account = engine.get_account(name)
    if account is None:
        raise HTTPException(status_code=404, detail="paper account not found")
    return {
        "account": account_summary(db, account),
        "positions": positions(db, account),
        "orders": orders(db, account, limit=limit),
        "fills": fills(db, account, limit=limit),
        "runs": runs(db, account, limit=30),
    }


@router.get("/accounts/{name}/equity")
def account_equity(
    name: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    engine = PaperEngine(db, settings, require_paper_mode=False)
    account = engine.get_account(name)
    if account is None:
        raise HTTPException(status_code=404, detail="paper account not found")
    return {"name": account.name, "equity": equity_curve(db, account)}


@router.post("/accounts", status_code=201)
def create_account(
    body: CreateAccountRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_paper(settings)
    engine = PaperEngine(db, settings)
    try:
        account = engine.create_account(
            name=body.name,
            strategy_name=body.strategy_name,
            params=body.params,
            initial_cash=body.initial_cash,
            rebalance=body.rebalance,
            notes=body.notes,
        )
        db.commit()
    except (PaperEngineError, StrategyError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return account_summary(db, account)


@router.post("/accounts/{name}/status")
def set_account_status(
    name: str,
    status: Annotated[str, Query(pattern="^(active|paused)$")],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    _require_paper(settings)
    engine = PaperEngine(db, settings)
    account = engine.get_account(name)
    if account is None:
        raise HTTPException(status_code=404, detail="paper account not found")
    account.status = status
    db.commit()
    return account_summary(db, account)


@router.post("/run", status_code=202)
def run_paper(
    body: PaperRunRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> dict[str, object]:
    _require_paper(settings)
    if jobs.running("paper_run") or jobs.running("market_fetch"):
        raise HTTPException(
            status_code=409, detail="a paper run or fetch is already running"
        )

    def runner() -> dict[str, Any]:
        session = factory()
        try:
            if body.fetch:
                from quant_platform.marketdata.providers import (
                    YFinanceMarketDataProvider,
                )
                from quant_platform.marketdata.service import (
                    fetch_and_store_market_data,
                )
                from quant_platform.marketdata.universe import resolve_universe

                fetch_and_store_market_data(
                    session,
                    YFinanceMarketDataProvider(),
                    resolve_universe(None),
                    source_name=settings.market_data_source_name,
                )
            engine = PaperEngine(session, settings)
            accounts = None
            if body.accounts:
                accounts = []
                for name in body.accounts:
                    account = engine.get_account(name)
                    if account is None:
                        raise PaperEngineError(f"unknown paper account {name!r}")
                    accounts.append(account)
            report = engine.run_all(replay_from=body.replay_from, accounts=accounts)
            session.commit()
            return report.as_mapping()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    job = jobs.submit("paper_run", runner, params=body.model_dump(mode="json"))
    return job.as_mapping(include_result=False)
