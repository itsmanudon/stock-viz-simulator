"""The Journal's unit of account: one closing execution.

A Journal *trade* is an execution that realized a gain or loss — an equity sell
(``trades.realized_pnl IS NOT NULL``) or an option contract that reached a
terminal status. Buys open exposure and realize nothing, so they are not
trades here; counting them would make "win rate" meaningless.

This is a fill-level definition, not a round-trip one: a scale-out that sells a
position in three pieces is three trades. It matches exactly what
``trades.realized_pnl`` already measures, so no lot-matching layer is invented
on top of the ledger. See ``docs/TRADING_JOURNAL.md``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal


class ExecutionKind(enum.StrEnum):
    EQUITY = "equity"
    OPTION = "option"


@dataclass(frozen=True, slots=True)
class SignalAtEntry:
    """The rule-based score that stood for this ticker when the trade was made.

    Reserved for opening-decision provenance. No signal is currently attached:
    a closing fill does not identify which opening decisions it realizes.
    """

    score: int
    max_score: int
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class JournalExecution:
    """One realized gain or loss, normalized across equities and options.

    ``realized_pnl`` is USD, at the FX rate captured when the trade filled.
    ``session_date`` is the New York trading session the execution belongs to,
    not its UTC calendar date.
    """

    kind: ExecutionKind
    reference_id: int
    ticker: str
    session_date: date_type
    executed_at: datetime
    realized_pnl: Decimal

    # Equity legs.
    side: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    avg_cost: Decimal | None = None
    currency: str = "USD"

    # Option legs.
    option_type: str | None = None
    strike: Decimal | None = None
    expiry: date_type | None = None
    contracts: int | None = None
    premium_paid: Decimal | None = None
    proceeds: Decimal | None = None
    option_status: str | None = None

    signal_at_entry: SignalAtEntry | None = None
