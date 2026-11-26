"""Reconciliation of stored intraday bars (A6.1): ``stockviz.cli intraday-reconcile``.

Each session's stored bars are resampled to one daily bar (open = the first
bar's open, high/low the extremes, close = the last bar's close, volume the
sum; the session is the bar's venue date) and compared with a reference:

- ``daily`` (default): the stored daily ``price_bars`` (``1d``, any source);
- ``60m``: the same instrument's stored 60-minute bars, resampled the same
  way (two of the owner's files checked against each other).

A session matches when open, high, low and close are each within
``price_tol_pct`` of the reference and, where volume is real (not an index,
reference volume above 0), the volume ratio is within ``volume_tol_pct``.
Reports give percentages and counts, never a price.

Expect differences against exchange daily bars: an NSE daily close is the
volume-weighted price of the last 30 minutes, not the last trade, and the
open comes from the pre-open auction, which minute files may not hold.

:func:`reconcile_moneycontrol` checks a MoneyControl file (never stored)
against the stored bulk 1-minute bars: the same UTC instants, minute by
minute, and per session.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from stockviz.models.instrument import Instrument
from stockviz.models.intraday import IntradayBar
from stockviz.models.market import PriceBar
from stockviz.services.instruments import instrument_ids
from stockviz.services.intraday.files import KINDS, ParseProblems, read_rows
from stockviz.services.markets.calendar import session_minutes, venue_zone

FIELDS = ("open", "high", "low", "close")
DEFAULT_PRICE_TOL_PCT = 0.5
DEFAULT_VOLUME_TOL_PCT = 10.0
MATCH_RATE_FOR_SYMBOL = 0.99


@dataclass(frozen=True)
class DailyAgg:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    bars: int = 1


def resample_daily(
    bars: Iterable[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]], venue: str
) -> dict[date, DailyAgg]:
    """Bars (naive UTC open instant, O, H, L, C, V), in any order, to one bar per venue date."""
    zone: ZoneInfo = venue_zone(venue)
    grouped: dict[date, list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]] = {}
    for bar in bars:
        day = bar[0].replace(tzinfo=UTC).astimezone(zone).date()
        grouped.setdefault(day, []).append(bar)
    out: dict[date, DailyAgg] = {}
    for day, items in grouped.items():
        items.sort(key=lambda b: b[0])
        out[day] = DailyAgg(
            open=items[0][1],
            high=max(b[2] for b in items),
            low=min(b[3] for b in items),
            close=items[-1][4],
            volume=sum(b[5] for b in items),
            bars=len(items),
        )
    return out


def pct_diff(value: Decimal, reference: Decimal) -> float:
    """|value - reference| / reference, in percent (0 when both are 0)."""
    if reference == 0:
        return 0.0 if value == 0 else float("inf")
    return float(abs(value - reference) / abs(reference) * 100)


@dataclass
class Mismatch:
    day: date
    field: str
    diff_pct: float


@dataclass
class SymbolReconciliation:
    ticker: str
    compared: int = 0
    matched: int = 0
    only_intraday: int = 0
    only_reference: int = 0
    field_mismatches: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    volume_mismatches: int = 0
    volume_checked: bool = True
    worst: dict[str, float] = field(default_factory=dict)
    median_volume_ratio: float | None = None
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def match_rate(self) -> float | None:
        return self.matched / self.compared if self.compared else None

    @property
    def matches(self) -> bool:
        rate = self.match_rate
        return rate is not None and rate >= MATCH_RATE_FOR_SYMBOL


def compare(
    ticker: str,
    intraday: dict[date, DailyAgg],
    reference: dict[date, DailyAgg],
    *,
    price_tol_pct: float = DEFAULT_PRICE_TOL_PCT,
    volume_tol_pct: float = DEFAULT_VOLUME_TOL_PCT,
    check_volume: bool = True,
    keep: int = 10,
) -> SymbolReconciliation:
    """Session by session: how many agree within the tolerances, and the worst differences."""
    result = SymbolReconciliation(ticker=ticker, volume_checked=check_volume)
    result.only_intraday = len(intraday.keys() - reference.keys())
    result.only_reference = len(reference.keys() - intraday.keys())
    ratios: list[float] = []
    for day in sorted(intraday.keys() & reference.keys()):
        mine, ref = intraday[day], reference[day]
        result.compared += 1
        ok = True
        for name in FIELDS:
            diff = pct_diff(getattr(mine, name), getattr(ref, name))
            result.worst[name] = max(result.worst.get(name, 0.0), diff)
            if diff > price_tol_pct:
                ok = False
                result.field_mismatches[name] += 1
                result.mismatches.append(Mismatch(day, name, diff))
        if check_volume and ref.volume > 0:
            ratio = mine.volume / ref.volume
            ratios.append(ratio)
            diff = abs(ratio - 1) * 100
            result.worst["volume"] = max(result.worst.get("volume", 0.0), diff)
            if diff > volume_tol_pct:
                ok = False
                result.volume_mismatches += 1
                result.mismatches.append(Mismatch(day, "volume", diff))
        if ok:
            result.matched += 1
    if ratios:
        ratios.sort()
        result.median_volume_ratio = ratios[len(ratios) // 2]
    result.mismatches.sort(key=lambda m: -m.diff_pct)
    del result.mismatches[keep:]
    return result


# --- database reads -------------------------------------------------------------


def _intraday_rows(session: Session, instrument_id: int, feed: str, interval: str):
    stmt = sa_select(
        col(IntradayBar.ts),
        col(IntradayBar.open),
        col(IntradayBar.high),
        col(IntradayBar.low),
        col(IntradayBar.close),
        col(IntradayBar.volume),
    ).where(
        col(IntradayBar.instrument_id) == instrument_id,
        col(IntradayBar.feed) == feed,
        col(IntradayBar.interval) == interval,
    )
    return [tuple(r) for r in session.execute(stmt).all()]


def _daily_reference(session: Session, instrument_id: int) -> dict[date, DailyAgg]:
    stmt = sa_select(
        col(PriceBar.ts),
        col(PriceBar.open),
        col(PriceBar.high),
        col(PriceBar.low),
        col(PriceBar.close),
        col(PriceBar.volume),
    ).where(col(PriceBar.instrument_id) == instrument_id, col(PriceBar.interval) == "1d")
    # Daily ts is the session date at naive midnight (bar_semantics.session_label).
    return {
        ts.date(): DailyAgg(o, h, lo, c, int(v)) for ts, o, h, lo, c, v in session.execute(stmt)
    }


def stored_instruments(session: Session, feed: str, interval: str) -> list[tuple[int, str]]:
    """(instrument id, ticker) for every instrument with stored bars of this feed and interval."""
    from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier

    ids = session.exec(
        select(IntradayBar.instrument_id)
        .where(col(IntradayBar.feed) == feed, col(IntradayBar.interval) == interval)
        .distinct()
    ).all()
    if not ids:
        return []
    names = dict(
        session.exec(
            select(InstrumentIdentifier.instrument_id, InstrumentIdentifier.value).where(
                col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
                col(InstrumentIdentifier.valid_to).is_(None),
                col(InstrumentIdentifier.instrument_id).in_(ids),
            )
        ).all()
    )
    return sorted(((i, names.get(i, f"#{i}")) for i in ids), key=lambda p: p[1])


def _venue(ticker: str) -> str:
    """The ticker's venue; Sensex (no suffix) is BSE's."""
    from stockviz.services.markets.calendar import venue_for_ticker

    return "XBOM" if ticker.upper() == "^BSESN" else venue_for_ticker(ticker)


def reconcile(
    session: Session,
    *,
    tickers: Sequence[str] | None = None,
    feed: str = "file",
    interval: str = "1m",
    against: str = "daily",
    price_tol_pct: float = DEFAULT_PRICE_TOL_PCT,
    volume_tol_pct: float = DEFAULT_VOLUME_TOL_PCT,
) -> list[SymbolReconciliation]:
    """One report per instrument holding ``feed``/``interval`` bars (or only ``tickers``)."""
    if against not in {"daily", "60m"}:
        raise ValueError("against must be 'daily' or '60m'")
    targets = stored_instruments(session, feed, interval)
    if tickers:
        wanted = {t.upper() for t in tickers}
        targets = [(i, t) for i, t in targets if t.upper() in wanted]
    reports: list[SymbolReconciliation] = []
    for instrument_id, ticker in targets:
        venue = _venue(ticker)
        mine = resample_daily(_intraday_rows(session, instrument_id, feed, interval), venue)
        if against == "daily":
            ref = _daily_reference(session, instrument_id)
        else:
            ref = resample_daily(_intraday_rows(session, instrument_id, feed, "60m"), venue)
        asset_type = session.exec(
            select(Instrument.asset_type).where(col(Instrument.id) == instrument_id)
        ).first()
        reports.append(
            compare(
                ticker,
                mine,
                ref,
                price_tol_pct=price_tol_pct,
                volume_tol_pct=volume_tol_pct,
                check_volume=asset_type != "index",
            )
        )
    return reports


# --- MoneyControl --------------------------------------------------------------


@dataclass
class MoneyControlReport:
    file_name: str
    ticker: str
    status: str = "compared"  # compared | unmatched | no_stored_bars | failed
    error: str | None = None
    rows: int = 0
    invalid: int = 0
    off_session: int = 0
    off_session_with_volume: int = 0
    in_session: int = 0
    matched_instants: int = 0
    only_file: int = 0
    only_stored: int = 0
    close_mismatches: int = 0
    max_close_diff_pct: float = 0.0
    daily: SymbolReconciliation | None = None


def reconcile_moneycontrol(
    session: Session,
    path: Path,
    ticker: str,
    *,
    price_tol_pct: float = DEFAULT_PRICE_TOL_PCT,
    volume_tol_pct: float = DEFAULT_VOLUME_TOL_PCT,
) -> MoneyControlReport:
    """Compare one MoneyControl file with the stored bulk 1-minute bars of its instrument."""
    from stockviz.services.intraday.load import indian_venue

    kind = KINDS["moneycontrol"]
    report = MoneyControlReport(file_name=path.name, ticker=ticker)
    venue = indian_venue(ticker)
    problems = ParseProblems()
    try:
        rows = list(read_rows(path, kind, problems))
    except (ValueError, UnicodeDecodeError) as exc:
        report.status = "failed"
        report.error = str(exc)
        return report
    report.invalid = problems.total
    report.rows = len(rows) + problems.total
    in_session = []
    hours_by_day = {}
    for row in rows:
        day = row.local_ts.date()
        if day not in hours_by_day:
            hours_by_day[day] = session_minutes(day, venue)
        hours = hours_by_day[day]
        if hours is not None and hours.contains(row.ts.replace(tzinfo=UTC)):
            in_session.append(row)
        else:
            report.off_session += 1
            report.off_session_with_volume += row.volume > 0
    report.in_session = len(in_session)
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    if instrument_id is None:
        report.status = "unmatched"
        return report
    if not in_session:
        report.status = "no_stored_bars"
        return report
    lo, hi = min(r.ts for r in in_session), max(r.ts for r in in_session)
    stored = {
        ts: (o, h, low, c, v)
        for ts, o, h, low, c, v in _intraday_rows(session, instrument_id, "file", "1m")
        if lo <= ts <= hi
    }
    if not stored:
        report.status = "no_stored_bars"
        return report
    file_instants = set()
    for row in in_session:
        file_instants.add(row.ts)
        mine = stored.get(row.ts)
        if mine is None:
            report.only_file += 1
            continue
        report.matched_instants += 1
        diff = pct_diff(row.close, mine[3])
        report.max_close_diff_pct = max(report.max_close_diff_pct, diff)
        if diff > price_tol_pct:
            report.close_mismatches += 1
    report.only_stored = len(stored.keys() - file_instants)
    asset_type = session.exec(
        select(Instrument.asset_type).where(col(Instrument.id) == instrument_id)
    ).first()
    file_daily = resample_daily(
        ((r.ts, r.open, r.high, r.low, r.close, r.volume) for r in in_session), venue
    )
    stored_daily = resample_daily(((ts, *v) for ts, v in stored.items()), venue)
    report.daily = compare(
        ticker,
        file_daily,
        stored_daily,
        price_tol_pct=price_tol_pct,
        volume_tol_pct=volume_tol_pct,
        check_volume=asset_type != "index",
    )
    return report
