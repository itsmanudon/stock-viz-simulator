"""Volume profile (A6.7, M2.9): workspace ``docs/a6-design-note.md``.

How much volume traded at each price over a range of bars, with the point of
control (POC) and the value area (VAH/VAL). Pure: :func:`build_profile`
takes ``(high, low, volume)`` triples; :func:`load_profile` picks the bars.

**Spreading.** No stored bar says at which prices its volume traded, so each
bar's volume is spread evenly over its high-low range: a bin gets the share
of the bar's range that falls inside it. A bar with no range (high = low)
puts all its volume in the bin holding that price. That is an approximation
on minute bars and a coarse one on daily bars; the API says so in ``note``
and the badges.

**Bins.** ``bins`` equal slices from the lowest low to the highest high of the
range. A price on a bin edge belongs to the bin above it, except the highest
high, which is in the top bin. A range with one price (every high and low
equal) is one bin.

**POC.** The bin with the most volume. A tie goes to the bin nearest the
middle of the price range, then to the lower one.

**Value area.** From the POC outwards, one bin at a time: the side whose next
bin has more volume is added (a tie adds the bin above), until the bins
taken hold at least ``value_area`` (default 70%) of the total volume. VAL is
the low edge of the lowest bin taken and VAH the high edge of the highest.

**Bars.** Minute bars (``intraday_bars``, ``1m``) when every daily session in
the range has minutes on the chosen feed ("From minute bars"); otherwise the
stored daily bars ("EOD approximation"). The default feed is the best one
stored (``FEED_RANK``: SIP first), and an IEX profile is labelled "IEX volume
only". An index's volume is not real (stored as 0), so it gets no profile
(:class:`NoProfile`, the router's 409); nor does a range whose volume sums
to 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.models.instrument import Instrument
from stockviz.models.intraday import IntradayBar
from stockviz.services.bars.intraday import FEED_RANK, coverage
from stockviz.services.bars.resample import bar_date
from stockviz.services.markets.calendar import venue_zone

DEFAULT_BINS = 24
MIN_BINS = 4
MAX_BINS = 200
DEFAULT_VALUE_AREA = 0.7
DEFAULT_LOOKBACK = timedelta(days=365)
MAX_MINUTE_ROWS = 300_000
"""Past this many stored minutes the range is profiled from daily bars."""

BADGE_MINUTES = "From minute bars"
BADGE_EOD = "EOD approximation"
BADGE_IEX = "IEX volume only"

NOTE_SPREAD = (
    "Each bar's volume is spread evenly over its high-low range, so the profile "
    "is an approximation."
)
NOTE_EOD = (
    "Minute bars do not cover the whole range, so the profile is built from daily "
    "bars: each session's volume is spread over its whole day's range."
)
NOTE_TOO_LONG = (
    "The range holds too many minute bars, so the profile is built from daily bars: "
    "each session's volume is spread over its whole day's range."
)

_PRICE = Decimal("0.000001")

Triple = tuple[Decimal, Decimal, int]
"""(high, low, volume) of one bar."""


class NoProfile(ValueError):
    """No profile is offered for this symbol or range (the router's 409)."""


class NoBars(LookupError):
    """No bars are stored in the range (the router's 404)."""


@dataclass(frozen=True)
class ProfileBin:
    low: Decimal
    high: Decimal
    volume: float


@dataclass(frozen=True)
class Profile:
    bins: list[ProfileBin]
    poc: int
    """Index of the POC bin in ``bins``."""
    value_low: int
    value_high: int
    """Indices of the lowest and highest bins in the value area."""
    total_volume: float
    value_volume: float

    @property
    def poc_price(self) -> Decimal:
        b = self.bins[self.poc]
        return ((b.low + b.high) / 2).quantize(_PRICE, ROUND_HALF_UP)

    @property
    def val(self) -> Decimal:
        return self.bins[self.value_low].low

    @property
    def vah(self) -> Decimal:
        return self.bins[self.value_high].high


def _edges(lo: Decimal, hi: Decimal, bins: int) -> list[Decimal]:
    step = (hi - lo) / bins
    return [(lo + step * i).quantize(_PRICE, ROUND_HALF_UP) for i in range(bins)] + [hi]


def build_profile(
    bars: Sequence[Triple], *, bins: int = DEFAULT_BINS, value_area: float = DEFAULT_VALUE_AREA
) -> Profile:
    """The profile of ``bars`` (see the module rules). Raises :class:`NoProfile`
    when there are no bars or their volume sums to 0."""
    rows = [(Decimal(h), Decimal(lo), int(v)) for h, lo, v in bars]
    total = sum(v for _, _, v in rows)
    if not rows or total <= 0:
        raise NoProfile("The bars in this range have no volume, so there is no profile.")
    if not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    lo = min(r[1] for r in rows)
    hi = max(r[0] for r in rows)
    count = 1 if hi == lo else bins
    edges = _edges(lo, hi, count) if count > 1 else [lo, hi]
    width = float(hi - lo) / count if count > 1 else 0.0
    volumes = [0.0] * count
    base = float(lo)

    def index_of(price: float) -> int:
        if width == 0:
            return 0
        return min(count - 1, max(0, int((price - base) // width)))

    for high, low, volume in rows:
        if volume <= 0:
            continue
        h, l_ = float(high), float(low)
        if h <= l_:
            volumes[index_of(l_)] += volume
            continue
        first, last = index_of(l_), index_of(h)
        span = h - l_
        for i in range(first, last + 1):
            bin_lo = base + width * i
            bin_hi = bin_lo + width if i < count - 1 else float(hi)
            overlap = min(h, bin_hi) - max(l_, bin_lo)
            if overlap > 0:
                volumes[i] += volume * overlap / span

    middle = (count - 1) / 2
    poc = max(range(count), key=lambda i: (volumes[i], -abs(i - middle), -i))
    target = value_area * total
    below, above = poc, poc
    taken = volumes[poc]
    # A tiny tolerance so 70% of a total made of float shares is reached.
    while taken < target - 1e-9 and (below > 0 or above < count - 1):
        up = volumes[above + 1] if above < count - 1 else -1.0
        down = volumes[below - 1] if below > 0 else -1.0
        if up >= down:
            above += 1
            taken += up
        else:
            below -= 1
            taken += down
    return Profile(
        bins=[ProfileBin(edges[i], edges[i + 1], volumes[i]) for i in range(count)],
        poc=poc,
        value_low=below,
        value_high=above,
        total_volume=float(total),
        value_volume=taken,
    )


# --- loading ---------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedProfile:
    profile: Profile
    source: str
    """``minutes`` or ``daily``."""
    feed: str | None
    bars: int
    start: datetime
    end: datetime
    badges: list[str]
    note: str


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _venue_day(ts: datetime, venue: str) -> date:
    return ts.replace(tzinfo=UTC).astimezone(venue_zone(venue)).date()


def _daily_rows(
    session: Session, instrument_id: int, first: date, last: date
) -> list[tuple[datetime, Decimal, Decimal, int]]:
    # Daily ``ts`` is the session label; a day either side covers any offset.
    rows = session.exec(
        select(col(PriceBar.ts), col(PriceBar.high), col(PriceBar.low), col(PriceBar.volume)).where(
            col(PriceBar.instrument_id) == instrument_id,
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= datetime.combine(first - timedelta(days=1), datetime.min.time()),
            col(PriceBar.ts) < datetime.combine(last + timedelta(days=2), datetime.min.time()),
        )
    ).all()
    return [(ts, Decimal(h), Decimal(lo), int(v)) for ts, h, lo, v in rows]


def load_profile(
    session: Session,
    instrument: Instrument,
    *,
    venue: str,
    start: datetime | None,
    end: datetime | None,
    feed: str | None,
    bins: int = DEFAULT_BINS,
    value_area: float = DEFAULT_VALUE_AREA,
    now: datetime | None = None,
) -> LoadedProfile:
    """The profile of ``instrument`` from ``start`` to ``end`` (instants; a
    naive value is UTC). Raises :class:`NoProfile` or :class:`NoBars`."""
    assert instrument.id is not None
    if instrument.asset_type == "index":
        raise NoProfile(
            f"{instrument.symbol} is an index: its stored volume is 0, not real volume, "
            "so no volume profile is offered."
        )
    end_at = _naive(end) if end is not None else _naive(now or datetime.now(UTC))
    start_at = _naive(start) if start is not None else end_at - DEFAULT_LOOKBACK
    if start_at > end_at:
        raise ValueError("from must be before to")
    first_day, last_day = _venue_day(start_at, venue), _venue_day(end_at, venue)

    daily = [
        r for r in _daily_rows(session, instrument.id, first_day, last_day)
        if first_day <= bar_date(r[0], venue) <= last_day
    ]  # fmt: skip
    daily_days = {bar_date(r[0], venue) for r in daily}

    cov = [c for c in coverage(session, instrument.id) if c.interval == "1m"]
    stored = [f for f in FEED_RANK if any(c.feed == f for c in cov)]
    if feed is not None and feed not in stored and not daily:
        raise NoBars(f"No minute bars from feed {feed!r} and no daily bars in this range.")
    chosen = feed if feed is not None else (stored[0] if stored else None)

    note = NOTE_EOD
    if chosen is not None and chosen in stored:
        minutes = session.exec(
            select(
                col(IntradayBar.ts),
                col(IntradayBar.high),
                col(IntradayBar.low),
                col(IntradayBar.volume),
            )
            .where(
                col(IntradayBar.instrument_id) == instrument.id,
                col(IntradayBar.feed) == chosen,
                col(IntradayBar.interval) == "1m",
                col(IntradayBar.ts) >= start_at,
                col(IntradayBar.ts) <= end_at,
            )
            .limit(MAX_MINUTE_ROWS + 1)
        ).all()
        minute_days = {_venue_day(ts, venue) for ts, *_ in minutes}
        if len(minutes) > MAX_MINUTE_ROWS:
            note = NOTE_TOO_LONG
        elif minutes and daily_days <= minute_days:
            badges = [BADGE_MINUTES] + ([BADGE_IEX] if chosen == "iex" else [])
            profile = build_profile(
                [(Decimal(h), Decimal(lo), int(v)) for _, h, lo, v in minutes],
                bins=bins,
                value_area=value_area,
            )
            return LoadedProfile(
                profile=profile,
                source="minutes",
                feed=chosen,
                bars=len(minutes),
                start=start_at,
                end=end_at,
                badges=badges,
                note=NOTE_SPREAD,
            )
    if not daily:
        raise NoBars("No bars are stored in this range.")
    profile = build_profile([(h, lo, v) for _, h, lo, v in daily], bins=bins, value_area=value_area)
    return LoadedProfile(
        profile=profile,
        source="daily",
        feed=None,
        bars=len(daily),
        start=start_at,
        end=end_at,
        badges=[BADGE_EOD],
        note=note,
    )


__all__ = [
    "BADGE_EOD",
    "BADGE_IEX",
    "BADGE_MINUTES",
    "DEFAULT_BINS",
    "DEFAULT_VALUE_AREA",
    "MAX_BINS",
    "MIN_BINS",
    "LoadedProfile",
    "NoBars",
    "NoProfile",
    "Profile",
    "ProfileBin",
    "build_profile",
    "load_profile",
]
