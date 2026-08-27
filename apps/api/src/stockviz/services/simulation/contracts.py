"""Pure execution-kernel domain types.

Frozen dataclasses so identical inputs compare equal and cannot be mutated
after construction. These are *not* SQLModel entities and must not grow
portfolio, user, FX, or database identity fields.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class SimulationOrderType(enum.StrEnum):
    """Order types the kernel can reason about.

    ``MARKET`` is the live ``POST /v1/trades`` path. The others match
    ``models.order.OrderType`` string values used by pending orders.
    """

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class FillStatus(enum.StrEnum):
    """Execution-domain outcome. Account failures are not represented here."""

    FILLED = "filled"
    NOT_TRIGGERED = "not_triggered"
    INELIGIBLE = "ineligible"


def require_decimal(value: object, *, field: str) -> Decimal:
    """Accept ``Decimal`` or ``int``; reject ``float`` so prices never go binary."""

    if isinstance(value, (bool, float)):
        raise TypeError(f"{field} must be Decimal, not {type(value).__name__}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{field} must be Decimal, got {type(value).__name__}")


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _require_ticker(value: str) -> str:
    ticker = value.strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")
    return ticker


def _require_positive(value: Decimal, *, field: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{field} must be greater than 0")
    return value


def _require_non_negative(value: Decimal, *, field: str) -> Decimal:
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """An OHLC observation that may influence execution from ``observed_at`` onward.

    ``observed_at`` is the earliest simulation time at which this snapshot is
    allowed to affect a fill. It is not "whatever timestamp the vendor stored."
    """

    ticker: str
    observed_at: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _require_ticker(self.ticker))
        object.__setattr__(
            self, "observed_at", _require_aware(self.observed_at, field="observed_at")
        )
        if not self.interval.strip():
            raise ValueError("interval must be non-empty")
        for name in ("open", "high", "low", "close", "volume"):
            quantized = require_decimal(getattr(self, name), field=name)
            object.__setattr__(self, name, quantized)
            _require_non_negative(quantized, field=name)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What the execution kernel needs to decide a fill. No account identity."""

    ticker: str
    side: OrderSide
    order_type: SimulationOrderType
    quantity: Decimal
    submitted_at: datetime
    limit_price: Decimal | None = None
    remaining_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _require_ticker(self.ticker))
        object.__setattr__(
            self, "submitted_at", _require_aware(self.submitted_at, field="submitted_at")
        )
        quantity = _require_positive(
            require_decimal(self.quantity, field="quantity"), field="quantity"
        )
        object.__setattr__(self, "quantity", quantity)
        remaining = (
            quantity
            if self.remaining_quantity is None
            else require_decimal(self.remaining_quantity, field="remaining_quantity")
        )
        remaining = _require_positive(remaining, field="remaining_quantity")
        if remaining > quantity:
            raise ValueError("remaining_quantity cannot exceed quantity")
        object.__setattr__(self, "remaining_quantity", remaining)

        if self.order_type is SimulationOrderType.MARKET:
            return
        if self.limit_price is None:
            raise ValueError(f"{self.order_type} orders require limit_price")
        price = _require_positive(
            require_decimal(self.limit_price, field="limit_price"), field="limit_price"
        )
        object.__setattr__(self, "limit_price", price)


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Versioned fill-model identifier. SIM-01 implements ``legacy_close`` only."""

    name: str
    model_version: str
    assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must be non-empty")
        if not self.model_version.strip():
            raise ValueError("model_version must be non-empty")


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """Explainability payload. Prices are omitted when they were not eligible to observe."""

    profile: str
    model_version: str
    reference_price: Decimal | None
    fill_price: Decimal | None
    reason: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FillDecision:
    status: FillStatus
    fill_quantity: Decimal
    fill_price: Decimal | None
    remaining_quantity: Decimal
    trace: ExecutionTrace

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fill_quantity", require_decimal(self.fill_quantity, field="fill_quantity")
        )
        object.__setattr__(
            self,
            "remaining_quantity",
            require_decimal(self.remaining_quantity, field="remaining_quantity"),
        )
        if self.fill_price is not None:
            object.__setattr__(
                self, "fill_price", require_decimal(self.fill_price, field="fill_price")
            )
        if self.fill_quantity < 0:
            raise ValueError("fill_quantity must be >= 0")
        if self.remaining_quantity < 0:
            raise ValueError("remaining_quantity must be >= 0")
