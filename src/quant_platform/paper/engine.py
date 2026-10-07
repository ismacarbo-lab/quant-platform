"""Daily paper-trading engine (fictional money, simulated fills).

For one account and one completed session ``D``:

1. Fill the orders decided at the previous run at ``D``'s open (plus
   slippage and commission) through the broker adapter.
2. Credit cash dividends whose ex-date is ``D`` for held positions.
3. Mark positions to ``D``'s close and store an equity snapshot.
4. If ``D`` is a rebalance date (or the account has never been invested),
   ask the strategy for target weights using prices ``<= D`` only and
   queue the resulting market orders for the next session.

Runs are idempotent per ``(account, session_date)``. ``replay_from`` lets
an account build a simulated track record from past sessions; those runs
are flagged ``replayed`` so the dashboard can tell them apart from
forward paper runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.backtesting.data import PricePanel, load_price_panel
from quant_platform.backtesting.engine import REBALANCE_FREQUENCIES, rebalance_mask
from quant_platform.core.config import Settings, get_settings
from quant_platform.marketdata.universe import (
    BENCHMARK_SYMBOL,
    CASH_SYMBOL,
    DEFAULT_HISTORY_START,
    DEFAULT_UNIVERSE,
    UniverseInstrument,
    universe_symbols,
)
from quant_platform.paper.broker import (
    QUANTITY_QUANTUM,
    BrokerAdapter,
    ExecutionPrices,
    FillResult,
    OrderIntent,
    SimulatedBroker,
)
from quant_platform.paper.models import (
    PaperAccount,
    PaperEquitySnapshot,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperRun,
)
from quant_platform.strategies.base import build_context
from quant_platform.strategies.registry import build_strategy, strategy_spec

MONEY_QUANTUM = Decimal("0.0001")
PRICE_QUANTUM = Decimal("0.00000001")
WEIGHT_QUANTUM = Decimal("0.000001")
MIN_TRADE_NOTIONAL = Decimal("25")
MIN_TRADE_WEIGHT = Decimal("0.001")


class PaperEngineError(RuntimeError):
    """Raised when the engine cannot run (mode, missing data, bad account)."""


@dataclass(frozen=True, slots=True)
class PaperAccountRunReport:
    account_name: str
    strategy_name: str
    session_date: date
    status: str
    replayed: bool
    rebalanced: bool
    orders_created: int
    fills_executed: int
    fills_rejected: int
    dividends_credited: Decimal
    equity: Decimal | None
    cash: Decimal | None
    message: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "account_name": self.account_name,
            "strategy_name": self.strategy_name,
            "session_date": self.session_date.isoformat(),
            "status": self.status,
            "replayed": self.replayed,
            "rebalanced": self.rebalanced,
            "orders_created": self.orders_created,
            "fills_executed": self.fills_executed,
            "fills_rejected": self.fills_rejected,
            "dividends_credited": format(self.dividends_credited, "f"),
            "equity": None if self.equity is None else format(self.equity, "f"),
            "cash": None if self.cash is None else format(self.cash, "f"),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class PaperRunReport:
    session_dates: tuple[date, ...]
    accounts: tuple[PaperAccountRunReport, ...] = field(default_factory=tuple)
    data_hash: str | None = None

    @property
    def ok(self) -> bool:
        return all(item.status != "error" for item in self.accounts)

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "paper_run_report",
            "ok": self.ok,
            "session_dates": [item.isoformat() for item in self.session_dates],
            "run_count": len(self.accounts),
            "error_count": sum(1 for item in self.accounts if item.status == "error"),
            "data_hash": self.data_hash,
            "accounts": [item.as_mapping() for item in self.accounts],
        }


class PaperEngine:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        broker: BrokerAdapter | None = None,
        universe: Sequence[UniverseInstrument] = DEFAULT_UNIVERSE,
        cash_symbol: str | None = CASH_SYMBOL,
        require_paper_mode: bool = True,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        if require_paper_mode and not self._settings.is_paper_mode:
            raise PaperEngineError(
                "paper engine requires APP_MODE=paper (fictional money, explicit)"
            )
        self._broker = broker
        self._universe = tuple(universe)
        self._cash_symbol = cash_symbol

    # ------------------------------------------------------------------ accounts
    def list_accounts(self) -> list[PaperAccount]:
        return list(
            self._session.scalars(select(PaperAccount).order_by(PaperAccount.name))
        )

    def get_account(self, name: str) -> PaperAccount | None:
        return self._session.scalar(
            select(PaperAccount).where(PaperAccount.name == name)
        )

    def create_account(
        self,
        *,
        name: str,
        strategy_name: str,
        params: dict[str, object] | None = None,
        initial_cash: Decimal | None = None,
        rebalance: str | None = None,
        commission_bps: Decimal | None = None,
        slippage_bps: Decimal | None = None,
        benchmark_symbol: str = BENCHMARK_SYMBOL,
        notes: str | None = None,
    ) -> PaperAccount:
        spec = strategy_spec(strategy_name)
        strategy = build_strategy(strategy_name, params)
        frequency = rebalance or self._settings.paper_rebalance
        if frequency not in REBALANCE_FREQUENCIES:
            raise PaperEngineError(f"rebalance must be one of {REBALANCE_FREQUENCIES}")
        cash = (
            initial_cash
            if initial_cash is not None
            else self._settings.paper_initial_cash
        )
        if cash <= 0:
            raise PaperEngineError("initial_cash must be positive")
        if self.get_account(name) is not None:
            raise PaperEngineError(f"paper account {name!r} already exists")
        account = PaperAccount(
            name=name.strip(),
            strategy_name=spec.name,
            params=dict(strategy.params()),
            currency="USD",
            initial_cash=cash,
            cash=cash,
            status="active",
            rebalance=frequency,
            commission_bps=(
                commission_bps
                if commission_bps is not None
                else self._settings.paper_commission_bps
            ),
            slippage_bps=(
                slippage_bps
                if slippage_bps is not None
                else self._settings.paper_slippage_bps
            ),
            benchmark_symbol=benchmark_symbol,
            notes=notes,
        )
        self._session.add(account)
        self._session.flush()
        return account

    def ensure_default_accounts(self) -> list[PaperAccount]:
        """Create one account per configured default strategy if none exist."""
        existing = self.list_accounts()
        if existing:
            return existing
        created: list[PaperAccount] = []
        for raw in self._settings.paper_default_strategies.split(","):
            name = raw.strip()
            if not name:
                continue
            created.append(self.create_account(name=name, strategy_name=name))
        return created

    # --------------------------------------------------------------------- data
    def load_panel(
        self, *, as_of: datetime | None = None, start: date = DEFAULT_HISTORY_START
    ) -> PricePanel:
        stamp = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
        return load_price_panel(
            self._session,
            source_name=self._settings.market_data_source_name,
            symbols=universe_symbols(self._universe),
            start=start,
            end=stamp.date(),
            as_of=stamp,
        )

    # --------------------------------------------------------------------- runs
    def run_all(
        self,
        *,
        panel: PricePanel | None = None,
        as_of: datetime | None = None,
        replay_from: date | None = None,
        accounts: Sequence[PaperAccount] | None = None,
    ) -> PaperRunReport:
        """Run every active account for the latest session (or a replay range)."""
        data = panel or self.load_panel(as_of=as_of)
        targets = (
            list(accounts) if accounts is not None else self.ensure_default_accounts()
        )
        sessions = pd.DatetimeIndex(data.closes.index)
        if sessions.empty:
            raise PaperEngineError("no sessions available in the price panel")
        latest = pd.Timestamp(sessions[-1])
        if replay_from is None:
            run_dates = [latest]
        else:
            start_stamp = pd.Timestamp(replay_from, tz="UTC")
            run_dates = [
                pd.Timestamp(item) for item in sessions[sessions >= start_stamp]
            ]
        reports: list[PaperAccountRunReport] = []
        for stamp in run_dates:
            for account in targets:
                if account.status != "active":
                    continue
                reports.append(
                    self.run_account(
                        account,
                        data,
                        session_date=stamp.date(),
                        replayed=stamp < latest,
                    )
                )
        return PaperRunReport(
            session_dates=tuple(item.date() for item in run_dates),
            accounts=tuple(reports),
            data_hash=data.data_hash,
        )

    def run_account(
        self,
        account: PaperAccount,
        panel: PricePanel,
        *,
        session_date: date,
        replayed: bool = False,
    ) -> PaperAccountRunReport:
        existing = self._session.scalar(
            select(PaperRun).where(
                PaperRun.account_id == account.id,
                PaperRun.session_date == session_date,
            )
        )
        if existing is not None:
            return self._report(
                account,
                session_date,
                status="skipped",
                replayed=existing.replayed,
                message="already run for this session",
            )
        stamp = pd.Timestamp(session_date, tz="UTC")
        if stamp not in panel.closes.index:
            return self._report(
                account,
                session_date,
                status="skipped",
                replayed=replayed,
                message="no market session on this date",
            )
        view = panel.truncated(stamp)
        broker = self._broker or SimulatedBroker(
            commission_bps=Decimal(account.commission_bps),
            slippage_bps=Decimal(account.slippage_bps),
        )
        try:
            fills_ok, fills_rejected = self._fill_pending_orders(
                account, view, stamp, broker
            )
            dividends = self._credit_dividends(account, view, stamp)
            positions_value, weights, closes = self._mark_to_market(
                account, view, stamp
            )
            equity = (Decimal(account.cash) + positions_value).quantize(
                MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            if account.started_on is None:
                account.started_on = session_date
            self._write_snapshot(
                account,
                view,
                stamp,
                equity=equity,
                positions_value=positions_value,
                weights=weights,
                replayed=replayed,
            )
            rebalanced, orders_created = self._maybe_rebalance(
                account, view, stamp, equity=equity, closes=closes
            )
            account.last_run_date = session_date
            account.last_equity = equity
            run = PaperRun(
                account_id=account.id,
                session_date=session_date,
                status="ok",
                replayed=replayed,
                rebalanced=rebalanced,
                orders_created=orders_created,
                fills_executed=fills_ok,
                dividends_credited=dividends,
                data_hash=panel.data_hash,
            )
            self._session.add(run)
            self._session.flush()
        except Exception as exc:
            self._session.rollback()
            return self._report(
                account,
                session_date,
                status="error",
                replayed=replayed,
                message=f"{type(exc).__name__}: {exc}",
            )
        return PaperAccountRunReport(
            account_name=account.name,
            strategy_name=account.strategy_name,
            session_date=session_date,
            status="ok",
            replayed=replayed,
            rebalanced=rebalanced,
            orders_created=orders_created,
            fills_executed=fills_ok,
            fills_rejected=fills_rejected,
            dividends_credited=dividends,
            equity=equity,
            cash=Decimal(account.cash),
        )

    # ------------------------------------------------------------------ helpers
    def _report(
        self,
        account: PaperAccount,
        session_date: date,
        *,
        status: str,
        replayed: bool,
        message: str,
    ) -> PaperAccountRunReport:
        return PaperAccountRunReport(
            account_name=account.name,
            strategy_name=account.strategy_name,
            session_date=session_date,
            status=status,
            replayed=replayed,
            rebalanced=False,
            orders_created=0,
            fills_executed=0,
            fills_rejected=0,
            dividends_credited=Decimal("0"),
            equity=None
            if account.last_equity is None
            else Decimal(account.last_equity),
            cash=Decimal(account.cash),
            message=message,
        )

    def _positions(self, account: PaperAccount) -> dict[str, PaperPosition]:
        rows = self._session.scalars(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
        return {row.symbol: row for row in rows}

    def _fill_pending_orders(
        self,
        account: PaperAccount,
        view: PricePanel,
        stamp: pd.Timestamp,
        broker: BrokerAdapter,
    ) -> tuple[int, int]:
        pending = list(
            self._session.scalars(
                select(PaperOrder)
                .where(
                    PaperOrder.account_id == account.id,
                    PaperOrder.status == "pending",
                    PaperOrder.session_date < stamp.date(),
                )
                .order_by(PaperOrder.created_at, PaperOrder.symbol)
            )
        )
        if not pending:
            return 0, 0
        opens: dict[str, Decimal] = {}
        row_index = int(view.raw_opens.index.searchsorted(stamp))
        row_values = view.raw_opens.to_numpy(dtype="float64")[row_index]
        for symbol, value in zip(view.raw_opens.columns, row_values, strict=True):
            number = float(value)
            if number == number and number > 0:  # not NaN
                opens[str(symbol)] = _decimal(number, PRICE_QUANTUM)
        intents = [
            OrderIntent(
                symbol=order.symbol,
                side=order.side,
                quantity=Decimal(order.quantity),
                target_weight=Decimal(order.target_weight),
                reference_price=Decimal(order.reference_price),
                reason=order.reason,
            )
            for order in pending
        ]
        fills = broker.execute(
            intents,
            prices=ExecutionPrices(session_date=stamp.date(), opens=opens),
            available_cash=Decimal(account.cash),
        )
        by_symbol = {fill.symbol: fill for fill in fills}
        positions = self._positions(account)
        filled = 0
        rejected = 0
        for order in pending:
            fill = by_symbol.get(order.symbol)
            if fill is None or not fill.filled:
                order.status = "rejected"
                why = fill.rejected_reason if fill is not None else "no_fill"
                order.reason = f"{order.reason or ''} rejected:{why}".strip()
                rejected += 1
                continue
            position = positions.get(order.symbol)
            if position is None:
                position = PaperPosition(
                    account_id=account.id,
                    symbol=order.symbol,
                    quantity=Decimal("0"),
                    average_cost=Decimal("0"),
                )
                self._session.add(position)
                positions[order.symbol] = position
            quantity = Decimal(position.quantity)
            if fill.side == "buy":
                total_cost = (
                    quantity * Decimal(position.average_cost) + fill.gross_notional
                )
                new_quantity = quantity + fill.quantity
                position.average_cost = (
                    (total_cost / new_quantity).quantize(
                        PRICE_QUANTUM, rounding=ROUND_HALF_EVEN
                    )
                    if new_quantity > 0
                    else Decimal("0")
                )
                position.quantity = new_quantity
            else:
                sell_quantity = min(fill.quantity, quantity)
                fill = _replace_quantity(fill, sell_quantity)
                position.quantity = quantity - sell_quantity
                if position.quantity <= QUANTITY_QUANTUM:
                    position.quantity = Decimal("0")
            account.cash = (Decimal(account.cash) + fill.cash_delta()).quantize(
                MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            order.status = "filled"
            self._session.add(
                PaperFill(
                    order_id=order.id,
                    account_id=account.id,
                    fill_date=stamp.date(),
                    symbol=order.symbol,
                    side=order.side,
                    quantity=fill.quantity,
                    price=fill.price,
                    reference_price=fill.reference_price,
                    commission=fill.commission,
                    slippage_cost=fill.slippage_cost,
                    broker=broker.name,
                )
            )
            filled += 1
        self._session.flush()
        return filled, rejected

    def _credit_dividends(
        self, account: PaperAccount, view: PricePanel, stamp: pd.Timestamp
    ) -> Decimal:
        events = view.dividends_on(stamp)
        if not events:
            return Decimal("0")
        positions = self._positions(account)
        total = Decimal("0")
        for symbol, cash_per_share in events.items():
            position = positions.get(symbol)
            if position is None or Decimal(position.quantity) <= 0:
                continue
            amount = (
                Decimal(position.quantity) * _decimal(cash_per_share, PRICE_QUANTUM)
            ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            total += amount
        if total > 0:
            account.cash = (Decimal(account.cash) + total).quantize(
                MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
        return total

    def _mark_to_market(
        self, account: PaperAccount, view: PricePanel, stamp: pd.Timestamp
    ) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
        closes: dict[str, Decimal] = {}
        for symbol in view.symbols:
            series = view.raw_closes[symbol].dropna()
            if series.empty:
                continue
            closes[symbol] = _decimal(float(series.iloc[-1]), PRICE_QUANTUM)
        positions_value = Decimal("0")
        values: dict[str, Decimal] = {}
        for symbol, position in self._positions(account).items():
            quantity = Decimal(position.quantity)
            if quantity <= 0:
                continue
            price = closes.get(symbol)
            if price is None:
                continue
            value = quantity * price
            values[symbol] = value
            positions_value += value
        positions_value = positions_value.quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        equity = Decimal(account.cash) + positions_value
        weights = {
            symbol: (value / equity).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN)
            for symbol, value in values.items()
            if equity > 0
        }
        return positions_value, weights, closes

    def _write_snapshot(
        self,
        account: PaperAccount,
        view: PricePanel,
        stamp: pd.Timestamp,
        *,
        equity: Decimal,
        positions_value: Decimal,
        weights: dict[str, Decimal],
        replayed: bool,
    ) -> None:
        previous = self._session.scalar(
            select(PaperEquitySnapshot)
            .where(
                PaperEquitySnapshot.account_id == account.id,
                PaperEquitySnapshot.session_date < stamp.date(),
            )
            .order_by(PaperEquitySnapshot.session_date.desc())
            .limit(1)
        )
        daily_return: Decimal | None = None
        if previous is not None and Decimal(previous.equity) > 0:
            daily_return = (equity / Decimal(previous.equity) - 1).quantize(
                Decimal("0.00000001"), rounding=ROUND_HALF_EVEN
            )
        benchmark_equity = self._benchmark_equity(account, view, stamp)
        self._session.add(
            PaperEquitySnapshot(
                account_id=account.id,
                session_date=stamp.date(),
                cash=Decimal(account.cash),
                positions_value=positions_value,
                equity=equity,
                daily_return=daily_return,
                benchmark_equity=benchmark_equity,
                weights={
                    symbol: format(value, "f") for symbol, value in weights.items()
                },
                replayed=replayed,
            )
        )
        self._session.flush()

    def _benchmark_equity(
        self, account: PaperAccount, view: PricePanel, stamp: pd.Timestamp
    ) -> Decimal | None:
        symbol = account.benchmark_symbol
        if symbol not in view.closes.columns or account.started_on is None:
            return None
        series = view.closes[symbol].dropna()
        start_stamp = pd.Timestamp(account.started_on, tz="UTC")
        base = series.loc[series.index >= start_stamp]
        if base.empty:
            return None
        start_price = float(base.iloc[0])
        last_price = float(series.iloc[-1])
        if start_price <= 0:
            return None
        return (
            Decimal(account.initial_cash)
            * _decimal(last_price / start_price, Decimal("0.000000001"))
        ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)

    def _maybe_rebalance(
        self,
        account: PaperAccount,
        view: PricePanel,
        stamp: pd.Timestamp,
        *,
        equity: Decimal,
        closes: dict[str, Decimal],
    ) -> tuple[bool, int]:
        index = pd.DatetimeIndex(view.closes.index)
        is_rebalance_day = bool(rebalance_mask(index, account.rebalance).loc[stamp])
        never_invested = not self._has_orders(account)
        if not is_rebalance_day and not never_invested:
            return False, 0
        strategy = build_strategy(account.strategy_name, dict(account.params))
        if len(index) < strategy.warmup_days():
            return False, 0
        context = build_context(
            view.closes, stamp, universe=self._universe, cash_symbol=self._cash_symbol
        )
        weights = strategy.target_weights(context)
        positions = self._positions(account)
        created = 0
        for symbol, raw_weight in weights.items():
            target_weight = _decimal(float(raw_weight), WEIGHT_QUANTUM)
            price = closes.get(str(symbol))
            held = positions.get(str(symbol))
            held_quantity = Decimal(held.quantity) if held is not None else Decimal("0")
            if price is None or price <= 0:
                continue
            target_value = equity * target_weight
            current_value = held_quantity * price
            delta_value = target_value - current_value
            if abs(delta_value) < max(MIN_TRADE_NOTIONAL, equity * MIN_TRADE_WEIGHT):
                continue
            quantity = (abs(delta_value) / price).quantize(
                QUANTITY_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            side = "buy" if delta_value > 0 else "sell"
            if side == "sell":
                quantity = min(quantity, held_quantity)
            if quantity <= 0:
                continue
            self._session.add(
                PaperOrder(
                    account_id=account.id,
                    session_date=stamp.date(),
                    symbol=str(symbol),
                    side=side,
                    quantity=quantity,
                    status="pending",
                    target_weight=target_weight,
                    reference_price=price,
                    reason=f"{account.strategy_name} target {target_weight}",
                )
            )
            created += 1
        self._session.flush()
        return True, created

    def _has_orders(self, account: PaperAccount) -> bool:
        return (
            self._session.scalar(
                select(PaperOrder.id)
                .where(PaperOrder.account_id == account.id)
                .limit(1)
            )
            is not None
        )


def _decimal(value: float, quantum: Decimal) -> Decimal:
    return Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)


def _replace_quantity(fill: FillResult, quantity: Decimal) -> FillResult:
    if quantity == fill.quantity:
        return fill
    ratio = quantity / fill.quantity if fill.quantity > 0 else Decimal("0")
    return replace(
        fill,
        quantity=quantity,
        commission=(fill.commission * ratio).quantize(Decimal("0.000001")),
        slippage_cost=(fill.slippage_cost * ratio).quantize(Decimal("0.000001")),
    )
