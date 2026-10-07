"""Broker seam. Only a simulated implementation exists (fictional fills)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Protocol

QUANTITY_QUANTUM = Decimal("0.0001")
PRICE_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: Decimal
    target_weight: Decimal
    reference_price: Decimal
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPrices:
    """Traded prices for the execution session (raw, not adjusted)."""

    session_date: date
    opens: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class FillResult:
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    reference_price: Decimal
    commission: Decimal
    slippage_cost: Decimal
    rejected_reason: str | None = None

    @property
    def filled(self) -> bool:
        return self.rejected_reason is None

    @property
    def gross_notional(self) -> Decimal:
        return self.quantity * self.price

    def cash_delta(self) -> Decimal:
        """Cash change for the account (negative for buys)."""
        if not self.filled:
            return Decimal("0")
        if self.side == "buy":
            return -(self.gross_notional + self.commission)
        return self.gross_notional - self.commission


class BrokerAdapter(Protocol):
    """Execute order intents for one session. Real brokers are not implemented."""

    @property
    def name(self) -> str: ...

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        prices: ExecutionPrices,
        available_cash: Decimal,
    ) -> list[FillResult]: ...


class SimulatedBroker:
    """Fills market orders at the session open plus slippage; charges commission.

    Sells execute first so their proceeds fund buys. Buys that exceed the
    available cash are scaled down; nothing ever goes short or levered.
    """

    name = "simulated"

    def __init__(self, *, commission_bps: Decimal, slippage_bps: Decimal) -> None:
        if commission_bps < 0 or slippage_bps < 0:
            raise ValueError("costs must be non-negative")
        self._commission_rate = commission_bps / Decimal("10000")
        self._slippage_rate = slippage_bps / Decimal("10000")

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        prices: ExecutionPrices,
        available_cash: Decimal,
    ) -> list[FillResult]:
        cash = available_cash
        results: list[FillResult] = []
        ordered = sorted(intents, key=lambda item: 0 if item.side == "sell" else 1)
        for intent in ordered:
            reference = prices.opens.get(intent.symbol)
            if reference is None or reference <= 0:
                results.append(self._rejected(intent, "no_execution_price"))
                continue
            if intent.side == "buy":
                price = (reference * (1 + self._slippage_rate)).quantize(
                    PRICE_QUANTUM, rounding=ROUND_HALF_EVEN
                )
                quantity = intent.quantity
                max_affordable = cash / (price * (1 + self._commission_rate))
                if max_affordable <= 0:
                    results.append(self._rejected(intent, "insufficient_cash"))
                    continue
                if quantity > max_affordable:
                    quantity = max_affordable.quantize(
                        QUANTITY_QUANTUM, rounding=ROUND_DOWN
                    )
                    if quantity <= 0:
                        results.append(self._rejected(intent, "insufficient_cash"))
                        continue
            else:
                price = (reference * (1 - self._slippage_rate)).quantize(
                    PRICE_QUANTUM, rounding=ROUND_HALF_EVEN
                )
                quantity = intent.quantity
            gross = quantity * price
            commission = (gross * self._commission_rate).quantize(
                MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            slippage_cost = (abs(price - reference) * quantity).quantize(
                MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            fill = FillResult(
                symbol=intent.symbol,
                side=intent.side,
                quantity=quantity,
                price=price,
                reference_price=reference,
                commission=commission,
                slippage_cost=slippage_cost,
            )
            cash += fill.cash_delta()
            results.append(fill)
        return results

    @staticmethod
    def _rejected(intent: OrderIntent, reason: str) -> FillResult:
        return FillResult(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=intent.reference_price,
            reference_price=intent.reference_price,
            commission=Decimal("0"),
            slippage_cost=Decimal("0"),
            rejected_reason=reason,
        )
