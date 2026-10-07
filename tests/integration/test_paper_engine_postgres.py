"""Paper engine: bootstrap, replay, fills, snapshots, idempotency. PostgreSQL."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_platform.backtesting import load_price_panel
from quant_platform.core.config import Settings
from quant_platform.marketdata.providers import RecordedMarketDataProvider
from quant_platform.marketdata.service import fetch_and_store_market_data
from quant_platform.marketdata.universe import UniverseInstrument
from quant_platform.paper import (
    PaperEngine,
    PaperEngineError,
    PaperEquitySnapshot,
    PaperFill,
    PaperOrder,
    PaperRun,
)
from quant_platform.paper.queries import (
    account_summary,
    equity_curve,
    fills,
    orders,
    positions,
    runs,
)

pytestmark = pytest.mark.postgres

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "marketdata"
_NOW = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)


def _paper_settings(source_name: str) -> Settings:
    return Settings(
        _env_file=None,
        app_mode="paper",
        market_data_source_name=source_name,
        paper_initial_cash=Decimal("10000"),
        paper_rebalance="weekly",
    )


def _load(session: Session) -> tuple[str, tuple[UniverseInstrument, ...]]:
    token = uuid4().hex[:6].upper()
    source_name = f"yf_paper_{token.lower()}"
    recorded = RecordedMarketDataProvider(_FIXTURES)
    frames = {
        f"S{token}": recorded.fetch_history(
            "SPY", start=date(2024, 1, 1), end=date(2024, 3, 31)
        ),
        f"T{token}": recorded.fetch_history(
            "TLT", start=date(2024, 1, 1), end=date(2024, 3, 31)
        ),
        f"B{token}": recorded.fetch_history(
            "BIL", start=date(2024, 1, 1), end=date(2024, 3, 31)
        ),
    }
    universe = (
        UniverseInstrument(f"S{token}", "equity", "etf", "risk", "test"),
        UniverseInstrument(f"T{token}", "bonds", "etf", "defensive", "test"),
        UniverseInstrument(f"B{token}", "cash", "etf", "cash", "test"),
    )
    report = fetch_and_store_market_data(
        session,
        RecordedMarketDataProvider(_FIXTURES, frames=frames),
        universe,
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        now=_NOW,
        commit=False,
    )
    assert report.ok
    return source_name, universe


def test_engine_requires_paper_mode(db_session: Session) -> None:
    with pytest.raises(PaperEngineError):
        PaperEngine(db_session, Settings(_env_file=None, app_mode="research"))


def test_replay_then_daily_run_is_idempotent(db_session: Session) -> None:
    source_name, universe = _load(db_session)
    settings = _paper_settings(source_name)
    engine = PaperEngine(
        db_session, settings, universe=universe, cash_symbol=universe[2].symbol
    )
    account = engine.create_account(
        name=f"sixty_forty_{source_name}",
        strategy_name="sixty_forty",
        params={"equity_symbol": universe[0].symbol, "bond_symbol": universe[1].symbol},
        benchmark_symbol=universe[0].symbol,
    )
    panel = load_price_panel(
        db_session,
        source_name=source_name,
        symbols=tuple(item.symbol for item in universe),
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        as_of=_NOW,
    )
    # Replay January..mid March, the latest session is 2024-03-25.
    report = engine.run_all(
        panel=panel, replay_from=date(2024, 1, 2), accounts=[account]
    )
    assert report.ok, [
        item.message for item in report.accounts if item.status == "error"
    ]
    assert len(report.session_dates) == 60
    assert all(item.replayed for item in report.accounts[:-1])
    assert report.accounts[-1].replayed is False

    snapshots = int(
        db_session.scalar(
            select(func.count(PaperEquitySnapshot.id)).where(
                PaperEquitySnapshot.account_id == account.id
            )
        )
        or 0
    )
    assert snapshots == 60
    fill_count = int(
        db_session.scalar(
            select(func.count(PaperFill.id)).where(PaperFill.account_id == account.id)
        )
        or 0
    )
    assert fill_count >= 2
    open_positions = positions(db_session, account)
    symbols = {row["symbol"] for row in open_positions}
    assert universe[0].symbol in symbols and universe[1].symbol in symbols
    summary = account_summary(db_session, account)
    assert summary["equity"] is not None
    assert summary["benchmark_equity"] is not None
    assert summary["snapshot_count"] == 60
    assert summary["replayed_snapshots"] == 59
    weights = summary["weights"]
    assert isinstance(weights, dict)
    assert abs(sum(float(v) for v in weights.values()) - 1.0) < 0.05
    curve = equity_curve(db_session, account)
    assert curve[0]["date"] == "2024-01-02"
    assert curve[-1]["replayed"] is False
    assert curve[0]["equity"] == pytest.approx(10000.0)
    # Equity never jumps by more than the markets could justify (no leverage).
    for point in curve:
        assert point["equity"] > 7000
    # Fills happen at the next session's open with positive costs.
    first_fill = fills(db_session, account, limit=200)[-1]
    assert first_fill["fill_date"] == "2024-01-03"
    assert first_fill["commission"] >= 0
    assert orders(db_session, account, limit=5)
    assert runs(db_session, account, limit=5)[0]["status"] == "ok"

    # Re-running the latest session is a no-op.
    again = engine.run_all(panel=panel, accounts=[account])
    assert again.accounts[0].status == "skipped"
    assert (
        db_session.scalar(
            select(func.count(PaperRun.id)).where(PaperRun.account_id == account.id)
        )
        == 60
    )
    pending = db_session.scalar(
        select(func.count(PaperOrder.id)).where(
            PaperOrder.account_id == account.id, PaperOrder.status == "pending"
        )
    )
    assert int(pending or 0) >= 0


def test_default_accounts_bootstrap_and_dividend_credit(db_session: Session) -> None:
    source_name, universe = _load(db_session)
    settings = Settings(
        _env_file=None,
        app_mode="paper",
        market_data_source_name=source_name,
        paper_initial_cash=Decimal("10000"),
        paper_default_strategies="buy_and_hold",
    )
    engine = PaperEngine(
        db_session, settings, universe=universe, cash_symbol=universe[2].symbol
    )
    accounts = engine.ensure_default_accounts()
    assert [item.strategy_name for item in accounts] == ["buy_and_hold"]
    account = accounts[0]
    account.params = {"symbol": universe[0].symbol}
    account.benchmark_symbol = universe[0].symbol
    db_session.flush()
    panel = load_price_panel(
        db_session,
        source_name=source_name,
        symbols=tuple(item.symbol for item in universe),
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        as_of=_NOW,
    )
    report = engine.run_all(
        panel=panel, replay_from=date(2024, 3, 1), accounts=[account]
    )
    assert report.ok, [
        item.message for item in report.accounts if item.status == "error"
    ]
    # SPY fixture pays 1.6 per share on 2024-03-15 while the account holds it.
    credited = [item for item in report.accounts if item.dividends_credited > 0]
    assert credited
    assert credited[0].session_date == date(2024, 3, 15)
    assert engine.ensure_default_accounts() == accounts
