"""Strategy catalog."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_platform.strategies import StrategyError, list_strategy_specs, strategy_spec

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
def strategies() -> dict[str, object]:
    return {"strategies": [spec.as_mapping() for spec in list_strategy_specs()]}


@router.get("/{name}")
def strategy(name: str) -> dict[str, object]:
    try:
        return strategy_spec(name).as_mapping()
    except StrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
