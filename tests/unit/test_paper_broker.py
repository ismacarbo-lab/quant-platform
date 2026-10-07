"""Simulated broker fills: slippage, commission, cash limits, long-only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quant_platform.paper.broker import (
    ExecutionPrices,
    OrderIntent,
    SimulatedBroker,
)


def _intent(symbol: str, side: str, quantity: str) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        target_weight=Decimal("0.5"),
        reference_price=Decimal("100"),
    )


def _prices(**opens: str) -> ExecutionPrices:
    return ExecutionPrices(
        session_date=date(2024, 1, 3),
        opens={symbol: Decimal(value) for symbol, value in opens.items()},
    )


def test_buy_pays_slippage_and_commission() -> None:
    broker = SimulatedBroker(commission_bps=Decimal("10"), slippage_bps=Decimal("5"))
    [fill] = broker.execute(
        [_intent("SPY", "buy", "10")],
        prices=_prices(SPY="100"),
        available_cash=Decimal("5000"),
    )
    assert fill.filled
    assert fill.price == Decimal("100.05")
    assert fill.quantity == Decimal("10")
    assert fill.commission == Decimal("1.0005")
    assert fill.slippage_cost == Decimal("0.5")
    assert fill.cash_delta() == -(Decimal("1000.5") + Decimal("1.0005"))


def test_sell_receives_less_than_reference() -> None:
    broker = SimulatedBroker(commission_bps=Decimal("0"), slippage_bps=Decimal("10"))
    [fill] = broker.execute(
        [_intent("SPY", "sell", "4")],
        prices=_prices(SPY="200"),
        available_cash=Decimal("0"),
    )
    assert fill.price == Decimal("199.8")
    assert fill.cash_delta() == Decimal("799.2")


def test_sells_fund_buys_and_buys_are_capped_by_cash() -> None:
    broker = SimulatedBroker(commission_bps=Decimal("0"), slippage_bps=Decimal("0"))
    fills = broker.execute(
        [_intent("QQQ", "buy", "20"), _intent("SPY", "sell", "5")],
        prices=_prices(SPY="100", QQQ="100"),
        available_cash=Decimal("500"),
    )
    by_symbol = {fill.symbol: fill for fill in fills}
    assert by_symbol["SPY"].filled
    # 500 cash + 500 proceeds = 1000 -> only 10 QQQ affordable.
    assert by_symbol["QQQ"].quantity == Decimal("10")
    assert fills[0].symbol == "SPY"  # sells execute first


def test_missing_price_rejects_order() -> None:
    broker = SimulatedBroker(commission_bps=Decimal("1"), slippage_bps=Decimal("1"))
    [fill] = broker.execute(
        [_intent("GLD", "buy", "1")],
        prices=_prices(SPY="100"),
        available_cash=Decimal("1000"),
    )
    assert not fill.filled
    assert fill.rejected_reason == "no_execution_price"
    assert fill.cash_delta() == 0


def test_no_cash_rejects_buy() -> None:
    broker = SimulatedBroker(commission_bps=Decimal("0"), slippage_bps=Decimal("0"))
    [fill] = broker.execute(
        [_intent("SPY", "buy", "1")],
        prices=_prices(SPY="100"),
        available_cash=Decimal("0"),
    )
    assert fill.rejected_reason == "insufficient_cash"


def test_negative_costs_rejected() -> None:
    with pytest.raises(ValueError):
        SimulatedBroker(commission_bps=Decimal("-1"), slippage_bps=Decimal("0"))
