"""FX lookup and conversion helpers.

All rates in ``fx_rates`` are USD-per-1-unit-of-foreign-currency, so converting
between any two currencies is two multiplications via the USD pivot:

    amount_to = amount_from * (usd_per_from) / (usd_per_to)

USD itself is treated as ``Decimal(1)`` without a DB hit. Missing days
(weekends/holidays) fall back to the most recent rate on-or-before the
requested date — a forward-fill that matches how the brokerage UI would
show a stale weekend quote.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import FxRate


def latest_rate(
    session: Session, currency: str, *, on_or_before: date_type | None = None
) -> Decimal:
    """USD-per-1-unit-of-``currency`` as of ``on_or_before`` (default today).

    Raises ``LookupError`` if no rate has ever been stored — caller usually
    treats that as "skip conversion" rather than an error.
    """
    if currency == "USD":
        return Decimal(1)

    cutoff = on_or_before or utcnow().date()
    row = session.exec(
        select(FxRate)
        .where(FxRate.currency == currency, FxRate.date <= cutoff)
        .order_by(FxRate.date.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if row is None:
        raise LookupError(f"No FX rate for {currency!r} on-or-before {cutoff}")
    return row.usd_rate


def convert(
    session: Session,
    amount: Decimal,
    *,
    from_currency: str,
    to_currency: str,
    on_or_before: date_type | None = None,
) -> Decimal:
    """Convert ``amount`` from ``from_currency`` to ``to_currency`` via USD.

    Same-currency conversions short-circuit. Conversions involving USD use
    only one rate; cross-currency conversions multiply two.
    """
    if from_currency == to_currency:
        return amount

    usd_per_from = latest_rate(session, from_currency, on_or_before=on_or_before)
    usd_per_to = latest_rate(session, to_currency, on_or_before=on_or_before)
    usd_amount = amount * usd_per_from
    return (usd_amount / usd_per_to) if usd_per_to != Decimal(0) else Decimal(0)
