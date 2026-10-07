"""Backtests read the PIT panel and persist results. Requires PostgreSQL."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.backtesting import BacktestConfig, load_price_panel
from quant_platform.backtesting.data import PricePanelError
from quant_platform.backtesting.runner import (
    get_strategy_backtest,
    latest_backtest_per_strategy,
    list_strategy_backtests,
    record_detail,
    record_summary,
    run_strategy_backtest,
)
from quant_platform.marketdata.providers import RecordedMarketDataProvider
from quant_platform.marketdata.service import fetch_and_store_market_data
from quant_platform.marketdata.universe import UniverseInstrument

pytestmark = pytest.mark.postgres

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "marketdata"
_NOW = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)


def _load_universe(session: Session) -> tuple[str, tuple[UniverseInstrument, ...]]:
    token = uuid4().hex[:6].upper()
    source_name = f"yf_bt_{token.lower()}"
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
    assert report.ok is True
    return source_name, universe


def test_panel_is_pit_and_dividend_adjusted(db_session: Session) -> None:
    source_name, universe = _load_universe(db_session)
    symbols = tuple(item.symbol for item in universe)
    panel = load_price_panel(
        db_session,
        source_name=source_name,
        symbols=symbols,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        as_of=_NOW,
    )
    assert panel.session_count == 60
    assert panel.symbols == symbols
    spy = symbols[0]
    # SPY fixture has one dividend on 2024-03-15: earlier bars are scaled down.
    assert float(panel.closes[spy].iloc[0]) < float(panel.raw_closes[spy].iloc[0])
    assert float(panel.closes[spy].iloc[-1]) == float(panel.raw_closes[spy].iloc[-1])
    early = load_price_panel(
        db_session,
        source_name=source_name,
        symbols=symbols,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        as_of=datetime(2024, 2, 1, tzinfo=UTC),
    )
    assert early.session_count < panel.session_count
    with pytest.raises(PricePanelError):
        load_price_panel(
            db_session,
            source_name=source_name,
            symbols=symbols,
            start=date(2030, 1, 1),
            end=date(2030, 12, 31),
            as_of=_NOW,
        )


def test_backtest_persists_and_lists(db_session: Session) -> None:
    source_name, universe = _load_universe(db_session)
    config = BacktestConfig(
        rebalance="weekly", universe=universe, cash_symbol=universe[2].symbol
    )
    outcome = run_strategy_backtest(
        db_session,
        strategy_name="sixty_forty",
        params={"equity_symbol": universe[0].symbol, "bond_symbol": universe[1].symbol},
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        as_of=_NOW,
        config=config,
        universe=universe,
        benchmark_name="buy_and_hold",
        walk_forward=False,
    )
    assert outcome.record_id is not None
    record = get_strategy_backtest(db_session, outcome.record_id)
    assert record is not None
    assert record.strategy_name == "sixty_forty"
    assert record.session_count == 60
    assert record.symbols == list(item.symbol for item in universe)
    assert record.equity_curve[0]["date"] == "2024-01-02"
    assert record.equity_curve[-1]["benchmark"] is not None
    summary = record_summary(record)
    assert summary["metrics"]["sessions"] == 60
    detail = record_detail(record)
    assert len(detail["equity_curve"]) == 60
    listed = list_strategy_backtests(db_session, strategy_name="sixty_forty", limit=5)
    assert any(item.id == outcome.record_id for item in listed)
    latest = {
        row.strategy_name: row for row in latest_backtest_per_strategy(db_session)
    }
    assert latest["sixty_forty"].id == outcome.record_id
