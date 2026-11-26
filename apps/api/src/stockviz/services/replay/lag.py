"""The 30-day lag for Indian replay sessions (A4.6, M9.1; design note question 4).

SEBI's rule for simulated trading on market prices: a session on an NSE
(``XNSE``) or BSE (``XBOM``) symbol must end at least ``REPLAY_MIN_LAG_DAYS``
(default 30) calendar days before today, today being the venue's date. Other
venues have no lag. The owner-only override is server configuration
(``REPLAY_LAG_OVERRIDE_USER_IDS``, empty by default): no request field can
relax it. There is no prize or leaderboard anywhere in replay.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from stockviz._time import utcnow
from stockviz.services.bars.resample import bar_date
from stockviz.services.fee_view import INDIAN_VENUES, fee_date
from stockviz.services.markets.calendar import venue_for_ticker
from stockviz.settings import get_settings


def lag_days_for(ticker: str) -> int:
    """The minimum lag for ``ticker``'s venue (0: none)."""
    if venue_for_ticker(ticker) not in INDIAN_VENUES:
        return 0
    return max(0, get_settings().replay_min_lag_days)


def venue_today(ticker: str, now: datetime | None = None) -> date:
    return fee_date(ticker, now or utcnow())


def latest_allowed_end(ticker: str, *, today: date | None = None) -> date | None:
    """The last end date the lag allows, or None when no lag applies."""
    days = lag_days_for(ticker)
    if days <= 0:
        return None
    return (today or venue_today(ticker)) - timedelta(days=days)


def lag_waived_for(user_id: int) -> bool:
    return user_id in get_settings().replay_lag_override_user_ids


def end_inside_lag(ticker: str, end_ts: datetime, *, today: date | None = None) -> date | None:
    """The cut-off date when the bar at ``end_ts`` ends inside the lag, else None."""
    cutoff = latest_allowed_end(ticker, today=today)
    if cutoff is None:
        return None
    end_day = bar_date(end_ts, venue_for_ticker(ticker))
    return cutoff if end_day > cutoff else None


__all__ = [
    "end_inside_lag",
    "lag_days_for",
    "lag_waived_for",
    "latest_allowed_end",
    "venue_today",
]
