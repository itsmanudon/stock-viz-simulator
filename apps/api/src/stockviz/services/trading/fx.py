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
from datetime import datetime
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


def fill_rate_floor(
    now: datetime, venue: str, *, settled_session: date_type | None = None
) -> date_type:
    """Oldest rate date a fill may convert at (audit MD-7, Phase 4.5).

    The session before the one the fill belongs to: the latest completed
    session of the instrument's venue for a market order, or the session being
    settled for a pending order. The nightly job stores each day's rate after
    the close, so one missed night is tolerated and two (an FX outage) refuse
    the fill instead of converting at a rate weeks old.
    """
    from stockviz.services.markets.calendar import latest_completed_session, previous_session

    anchor = settled_session or latest_completed_session(now, venue)
    return previous_session(anchor, venue)


def rate_for_fill(
    session: Session,
    currency: str,
    *,
    now: datetime,
    venue: str,
    settled_session: date_type | None = None,
) -> Decimal:
    """The newest rate on or before ``now``, refused if older than ``fill_rate_floor``.

    Raises ``LookupError`` when no rate exists and ``StaleFxRate`` when the
    newest one is too old.
    """
    if currency == "USD":
        return Decimal(1)
    row = session.exec(
        select(FxRate)
        .where(FxRate.currency == currency, FxRate.date <= now.date())
        .order_by(FxRate.date.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if row is None:
        raise LookupError(f"No FX rate for {currency!r} on-or-before {now.date()}")
    floor = fill_rate_floor(now, venue, settled_session=settled_session)
    if row.date < floor:
        raise StaleFxRate(
            f"The newest {currency} rate is from {row.date}; fills need one from {floor} or later"
        )
    return row.usd_rate


RATE_PLACES = Decimal("0.00000001")  # trades.fx_rate is Numeric(18, 8)


def base_rate(
    session: Session, currency: str, base: str, *, on_or_before: date_type | None = None
) -> Decimal:
    """Units of ``base`` per one unit of ``currency``, through the USD pivot.

    Phase 4.8: a portfolio's cash is in its base currency (USD or INR), so a
    fill, reservation or valuation converts into the base, not into USD. For a
    USD base this is exactly :func:`latest_rate`.
    """
    if currency == base:
        return Decimal(1)
    usd_per_from = latest_rate(session, currency, on_or_before=on_or_before)
    if base == "USD":
        return usd_per_from
    usd_per_base = latest_rate(session, base, on_or_before=on_or_before)
    return (usd_per_from / usd_per_base).quantize(RATE_PLACES)


def fill_rate_to_base(
    session: Session,
    currency: str,
    base: str,
    *,
    now: datetime,
    venue: str,
    settled_session: date_type | None = None,
) -> Decimal:
    """:func:`rate_for_fill` into ``base``: both legs must be fresh (MD-7)."""
    if currency == base:
        return Decimal(1)
    usd_per_from = rate_for_fill(
        session, currency, now=now, venue=venue, settled_session=settled_session
    )
    if base == "USD":
        return usd_per_from
    usd_per_base = rate_for_fill(
        session, base, now=now, venue=venue, settled_session=settled_session
    )
    return (usd_per_from / usd_per_base).quantize(RATE_PLACES)


class StaleFxRate(LookupError):
    """The newest stored rate is older than a fill may use (MD-7)."""


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
