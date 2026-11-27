"""India index options read from the stored daily summaries (A7.14, M6.1, M6.3).

Per underlying and series, per day:

- **ATM IV:** the mean of the ATM call's and put's IV at the day's last minute
  (one side when the other is missing).
- **Put-call skew:** IV of the put ``SKEW_OFFSET`` strikes below the money
  minus IV of the call as many strikes above (the files' offsets; not delta).
- **PCR (OI):** summed put OI over summed call OI across the stored offsets.
- **IV rank** over the stored window: (now - min) / (max - min) x 100, and the
  percentile: share of days below now. Both need ``MIN_DAYS`` days.

The files' IV comes as given (the vendor's model, not StockViz's); offsets are
relative to the money on each minute, so a strike changes as spot moves.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, select

from stockviz.models import FoDaily

SKEW_OFFSET = 2
MIN_DAYS = 60


@dataclass(frozen=True)
class DayPoint:
    day: date
    atm_iv: float | None
    skew: float | None
    pcr: float | None
    spot: float


@dataclass
class UnderlyingSummary:
    underlying: str
    series: str
    first: date
    last: date
    days: list[DayPoint]
    iv_now: float | None
    iv_rank: float | None
    iv_percentile: float | None
    smile: list[tuple[int, float | None, float | None]] = field(default_factory=list)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarise(rows: list[FoDaily]) -> list[UnderlyingSummary]:
    grouped: dict[tuple[str, str], dict[date, list[FoDaily]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in rows:
        grouped[(r.underlying, r.series)][r.day].append(r)
    out: list[UnderlyingSummary] = []
    for (und, series), by_day in sorted(grouped.items()):
        points: list[DayPoint] = []
        for day in sorted(by_day):
            cells = {(r.option_type, r.strike_offset): r for r in by_day[day]}
            atm = [c.iv for k in (("CE", 0), ("PE", 0)) if (c := cells.get(k)) and c.iv is not None]
            put = cells.get(("PE", -SKEW_OFFSET))
            call = cells.get(("CE", SKEW_OFFSET))
            skew = (
                put.iv - call.iv
                if put and call and put.iv is not None and call.iv is not None
                else None
            )
            ce_oi = sum(r.oi or 0 for r in by_day[day] if r.option_type == "CE")
            pe_oi = sum(r.oi or 0 for r in by_day[day] if r.option_type == "PE")
            spot = float(by_day[day][0].spot)
            points.append(DayPoint(day, _mean(atm), skew, pe_oi / ce_oi if ce_oi else None, spot))
        ivs = [p.atm_iv for p in points if p.atm_iv is not None]
        now = ivs[-1] if ivs else None
        rank = pct = None
        if now is not None and len(ivs) >= MIN_DAYS:
            lo, hi = min(ivs), max(ivs)
            rank = (now - lo) / (hi - lo) * 100 if hi > lo else None
            pct = sum(1 for v in ivs if v < now) / len(ivs) * 100
        last_day = max(by_day)
        last_cells = {(r.option_type, r.strike_offset): r.iv for r in by_day[last_day]}
        offsets = sorted({o for _t, o in last_cells})
        smile = [(o, last_cells.get(("CE", o)), last_cells.get(("PE", o))) for o in offsets]
        out.append(
            UnderlyingSummary(und, series, min(by_day), last_day, points, now, rank, pct, smile)
        )
    return out


def load_summaries(session: Session) -> list[UnderlyingSummary]:
    rows = list(session.exec(select(FoDaily).order_by(col(FoDaily.day))).all())
    return summarise(rows)
