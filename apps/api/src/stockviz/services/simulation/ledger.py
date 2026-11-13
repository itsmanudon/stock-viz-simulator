"""SimLedger: the simulated account replay and backtests share (Phase 5.1).

Pure, like the kernel: no Session, clock, FX lookup or I/O. It applies a
filled decision with the same arithmetic as live trading's
``services/trading/execute.apply_fill`` for one currency:

- a buy debits ``price x quantity`` (rounded to 6 places) plus fees and
  re-averages the position's cost: ``(avg x held + cost) / (held + bought)``;
- a sell credits the proceeds less fees, keeps the average cost, and realises
  ``(price - avg) x quantity``; a position sold to zero is removed.

``tests/test_sim_ledger.py`` runs one order sequence through ``apply_fill``
and through this ledger and requires the same cash, positions and P&L. Keep
the two in step: when they had separate copies, they drifted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from stockviz.services.simulation.contracts import OrderSide

MICROS = Decimal("0.000001")


class SimInsufficientCash(ValueError):
    """A simulated buy costs more than the simulated cash."""


class SimInsufficientPosition(ValueError):
    """A simulated sell is larger than the simulated holding."""


@dataclass
class SimPosition:
    quantity: Decimal
    avg_cost: Decimal


@dataclass(frozen=True)
class SimFill:
    side: OrderSide
    ticker: str
    quantity: Decimal
    price: Decimal
    cost: Decimal
    fees: Decimal
    realized_pnl: Decimal | None
    avg_cost_at_fill: Decimal | None


@dataclass
class SimLedger:
    cash: Decimal
    positions: dict[str, SimPosition] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal(0)
    fees_paid: Decimal = Decimal(0)

    def apply(
        self,
        side: OrderSide,
        ticker: str,
        quantity: Decimal,
        price: Decimal,
        *,
        fees: Decimal = Decimal(0),
    ) -> SimFill:
        """Apply one fill. Raises without changing anything if it cannot."""
        ticker = ticker.upper()
        cost = (price * quantity).quantize(MICROS)
        fees = fees.quantize(MICROS)
        position = self.positions.get(ticker)

        if side is OrderSide.BUY:
            needed = cost + fees
            if self.cash < needed:
                raise SimInsufficientCash(f"cash {self.cash:.2f}; order requires {needed:.2f}")
            self.cash = (self.cash - needed).quantize(MICROS)
            if position is None:
                self.positions[ticker] = SimPosition(quantity=quantity, avg_cost=price)
            else:
                total = position.avg_cost * position.quantity + cost
                held = position.quantity + quantity
                position.quantity = held
                position.avg_cost = (total / held).quantize(MICROS)
            self.fees_paid += fees
            return SimFill(side, ticker, quantity, price, cost, fees, None, None)

        held = position.quantity if position is not None else Decimal(0)
        if position is None or held < quantity:
            raise SimInsufficientPosition(f"held {held} {ticker}, cannot sell {quantity}")
        avg = position.avg_cost
        realized = ((price - avg) * quantity).quantize(MICROS)
        self.cash = (self.cash + cost - fees).quantize(MICROS)
        position.quantity = held - quantity
        if position.quantity == 0:
            del self.positions[ticker]
        self.realized_pnl += realized
        self.fees_paid += fees
        return SimFill(side, ticker, quantity, price, cost, fees, realized, avg)

    def market_value(self, closes: dict[str, Decimal]) -> Decimal:
        return sum(
            (p.quantity * closes[t] for t, p in self.positions.items() if t in closes),
            Decimal(0),
        )

    def equity(self, closes: dict[str, Decimal]) -> Decimal:
        return self.cash + self.market_value(closes)
