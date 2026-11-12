"""Server-side bounds on order inputs (audit LG-9).

Inputs were unbounded: a quantity of "NaN" passed the request model and then
raised a 500, and a seven-decimal quantity debited cash on the unrounded value
while the column (six decimals) stored a rounded one. Every amount a user can
send goes through :func:`check_amount`.
"""

from __future__ import annotations

from decimal import Decimal

MAX_DECIMAL_PLACES = 6
"""What the quantity and price columns store (``Numeric(..., 6)``)."""

MAX_QUANTITY = Decimal("1000000000")
MAX_PRICE = Decimal("1000000000")
MAX_OPTION_CONTRACTS = 1_000
MAX_OPTION_YEARS = 3


def check_amount(value: Decimal, *, name: str, maximum: Decimal) -> Decimal:
    """Return ``value`` if it is a finite, positive amount the columns can store.

    Raises ``ValueError`` with a message for the client otherwise.
    """
    if not value.is_finite():
        raise ValueError(f"{name} must be a number")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    if value > maximum:
        raise ValueError(f"{name} must be at most {maximum:,}")
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > MAX_DECIMAL_PLACES:
        raise ValueError(f"{name} can have at most {MAX_DECIMAL_PLACES} decimal places")
    return value
