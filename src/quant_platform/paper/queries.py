"""Read-side helpers for paper accounts (API and CLI). No writes here."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_platform.paper.models import (
    PaperAccount,
    PaperEquitySnapshot,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperRun,
)


def _money(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def account_summary(session: Session, account: PaperAccount) -> dict[str, object]:
    latest = session.scalar(
        select(PaperEquitySnapshot)
        .where(PaperEquitySnapshot.account_id == account.id)
        .order_by(PaperEquitySnapshot.session_date.desc())
        .limit(1)
    )
    first = session.scalar(
        select(PaperEquitySnapshot)
        .where(PaperEquitySnapshot.account_id == account.id)
        .order_by(PaperEquitySnapshot.session_date.asc())
        .limit(1)
    )
    snapshot_count = int(
        session.scalar(
            select(func.count(PaperEquitySnapshot.id)).where(
                PaperEquitySnapshot.account_id == account.id
            )
        )
        or 0
    )
    replayed_count = int(
        session.scalar(
            select(func.count(PaperEquitySnapshot.id)).where(
                PaperEquitySnapshot.account_id == account.id,
                PaperEquitySnapshot.replayed.is_(True),
            )
        )
        or 0
    )
    fills = int(
        session.scalar(
            select(func.count(PaperFill.id)).where(PaperFill.account_id == account.id)
        )
        or 0
    )
    equity = _money(None if latest is None else Decimal(latest.equity))
    initial = float(account.initial_cash)
    total_return = None if equity is None else equity / initial - 1.0
    benchmark_equity = _money(
        None
        if latest is None or latest.benchmark_equity is None
        else Decimal(latest.benchmark_equity)
    )
    benchmark_return = (
        None if benchmark_equity is None else benchmark_equity / initial - 1.0
    )
    max_drawdown = _max_drawdown(session, account)
    return {
        "id": str(account.id),
        "name": account.name,
        "strategy_name": account.strategy_name,
        "params": dict(account.params),
        "status": account.status,
        "currency": account.currency,
        "rebalance": account.rebalance,
        "commission_bps": float(account.commission_bps),
        "slippage_bps": float(account.slippage_bps),
        "benchmark_symbol": account.benchmark_symbol,
        "initial_cash": initial,
        "cash": float(account.cash),
        "equity": equity,
        "positions_value": _money(
            None if latest is None else Decimal(latest.positions_value)
        ),
        "total_return": total_return,
        "benchmark_equity": benchmark_equity,
        "benchmark_return": benchmark_return,
        "max_drawdown": max_drawdown,
        "started_on": None
        if account.started_on is None
        else account.started_on.isoformat(),
        "first_session": None if first is None else first.session_date.isoformat(),
        "last_run_date": (
            None if account.last_run_date is None else account.last_run_date.isoformat()
        ),
        "snapshot_count": snapshot_count,
        "replayed_snapshots": replayed_count,
        "fill_count": fills,
        "weights": {} if latest is None else dict(latest.weights),
        "notes": account.notes,
    }


def equity_curve(session: Session, account: PaperAccount) -> list[dict[str, object]]:
    rows = session.scalars(
        select(PaperEquitySnapshot)
        .where(PaperEquitySnapshot.account_id == account.id)
        .order_by(PaperEquitySnapshot.session_date)
    )
    return [
        {
            "date": row.session_date.isoformat(),
            "equity": float(row.equity),
            "cash": float(row.cash),
            "benchmark": _money(
                None if row.benchmark_equity is None else Decimal(row.benchmark_equity)
            ),
            "daily_return": _money(
                None if row.daily_return is None else Decimal(row.daily_return)
            ),
            "replayed": row.replayed,
        }
        for row in rows
    ]


def positions(session: Session, account: PaperAccount) -> list[dict[str, object]]:
    rows = session.scalars(
        select(PaperPosition)
        .where(PaperPosition.account_id == account.id, PaperPosition.quantity > 0)
        .order_by(PaperPosition.symbol)
    )
    return [
        {
            "symbol": row.symbol,
            "quantity": float(row.quantity),
            "average_cost": float(row.average_cost),
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


def orders(
    session: Session, account: PaperAccount, *, limit: int = 100
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(PaperOrder)
        .where(PaperOrder.account_id == account.id)
        .order_by(PaperOrder.session_date.desc(), PaperOrder.symbol)
        .limit(limit)
    )
    return [
        {
            "id": str(row.id),
            "session_date": row.session_date.isoformat(),
            "symbol": row.symbol,
            "side": row.side,
            "quantity": float(row.quantity),
            "status": row.status,
            "target_weight": float(row.target_weight),
            "reference_price": float(row.reference_price),
            "reason": row.reason,
        }
        for row in rows
    ]


def fills(
    session: Session, account: PaperAccount, *, limit: int = 100
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(PaperFill)
        .where(PaperFill.account_id == account.id)
        .order_by(PaperFill.fill_date.desc(), PaperFill.symbol)
        .limit(limit)
    )
    return [
        {
            "id": str(row.id),
            "fill_date": row.fill_date.isoformat(),
            "symbol": row.symbol,
            "side": row.side,
            "quantity": float(row.quantity),
            "price": float(row.price),
            "reference_price": float(row.reference_price),
            "commission": float(row.commission),
            "slippage_cost": float(row.slippage_cost),
            "broker": row.broker,
        }
        for row in rows
    ]


def runs(
    session: Session, account: PaperAccount, *, limit: int = 30
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(PaperRun)
        .where(PaperRun.account_id == account.id)
        .order_by(PaperRun.session_date.desc())
        .limit(limit)
    )
    return [
        {
            "session_date": row.session_date.isoformat(),
            "status": row.status,
            "replayed": row.replayed,
            "rebalanced": row.rebalanced,
            "orders_created": row.orders_created,
            "fills_executed": row.fills_executed,
            "dividends_credited": float(row.dividends_credited),
            "message": row.message,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _max_drawdown(session: Session, account: PaperAccount) -> float | None:
    values = list(
        session.scalars(
            select(PaperEquitySnapshot.equity)
            .where(PaperEquitySnapshot.account_id == account.id)
            .order_by(PaperEquitySnapshot.session_date)
        )
    )
    if not values:
        return None
    peak = float(values[0])
    worst = 0.0
    for raw in values:
        value = float(raw)
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst
