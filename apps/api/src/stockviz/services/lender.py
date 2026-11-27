"""Lender mode: price to book against return on equity (A7.13, M5.2).

The owner's 27 Nov 2026 answer: ship lender mode with P/B against ROE and the
industrial models switched off; GNPA, NNPA, NIM, CASA and CAR wait for a
source. For a bank or NBFC the book is the asset, so P/B is read against the
return the book earns.

- **Peers:** active symbols in the same market (``relative_strength.market_for``)
  whose sector is financial (``forensics.is_financial``), with a positive P/B
  and an ROE in the nightly ``symbol_metrics`` snapshot. Survivorship-biased:
  today's list.
- **Peer line:** ordinary least squares of P/B on ROE over the peers (5 at
  least); the symbol's gap is its P/B minus the line's value at its ROE.
  "Above the line" means the market pays more per point of ROE than for its
  peers: a description, not a verdict.
- **Justified P/B (Gordon):** (ROE - g) / (COE - g), with the cost of equity
  and growth as stated inputs (defaults 12% and 6% for India, 9% and 3%
  elsewhere); refused when COE <= g.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlmodel import Session, col, select

from stockviz.models import Symbol, SymbolMetrics
from stockviz.services.fundamentals.forensics import is_financial
from stockviz.services.relative_strength import market_for

MIN_PEERS = 5
DEFAULTS = {"IN": (0.12, 0.06), "US": (0.09, 0.03)}
KPI_NOTE = (
    "GNPA, NNPA, NIM, CASA and capital adequacy are not in any free source StockViz reads; "
    "they are left out until one is chosen."
)


class NotALender(ValueError):
    """The symbol's sector is not financial (409)."""


@dataclass(frozen=True)
class Peer:
    ticker: str
    pb: float
    roe: float


@dataclass
class LenderView:
    ticker: str
    market: str | None
    pb: float | None
    roe: float | None
    as_of: str | None
    peers: list[Peer] = field(default_factory=list)
    slope: float | None = None
    intercept: float | None = None
    line_pb: float | None = None
    gap: float | None = None
    coe: float = 0.0
    growth: float = 0.0
    justified_pb: float | None = None
    reasons: list[str] = field(default_factory=list)


def peer_line(peers: list[Peer]) -> tuple[float, float] | None:
    """(slope, intercept) of P/B on ROE (ROE in percent), or None under MIN_PEERS."""
    if len(peers) < MIN_PEERS:
        return None
    x = np.array([p.roe for p in peers])
    y = np.array([p.pb for p in peers])
    if float(np.ptp(x)) == 0.0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def justified_pb(roe_pct: float | None, coe: float, growth: float) -> float | None:
    if roe_pct is None or coe <= growth:
        return None
    return (roe_pct / 100 - growth) / (coe - growth)


def lender_view(
    session: Session, ticker: str, *, coe: float | None = None, growth: float | None = None
) -> LenderView:
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise LookupError(ticker)
    if not is_financial(symbol.sector):
        raise NotALender(
            f"{ticker} is not in a financial sector ({symbol.sector or 'none recorded'})"
        )
    market = market_for(ticker)
    default_coe, default_g = DEFAULTS.get(market or "", DEFAULTS["US"])
    view = LenderView(
        ticker=ticker,
        market=market,
        pb=None,
        roe=None,
        as_of=None,
        coe=default_coe if coe is None else coe,
        growth=default_g if growth is None else growth,
    )
    rows = session.exec(
        select(Symbol, SymbolMetrics)
        .join(SymbolMetrics, col(SymbolMetrics.ticker) == col(Symbol.ticker))
        .where(col(Symbol.is_active))
    ).all()
    for sym, metrics in rows:
        t, pb, roe = sym.ticker, metrics.pb, metrics.roe
        if t == ticker:
            view.pb, view.roe = pb, roe
            view.as_of = metrics.as_of.isoformat() if metrics.as_of else None
        if (
            market_for(t) == market
            and is_financial(sym.sector)
            and pb is not None
            and pb > 0
            and roe is not None
        ):
            view.peers.append(Peer(t, float(pb), float(roe)))
    view.peers.sort(key=lambda p: p.ticker)
    line = peer_line(view.peers)
    if line is None:
        view.reasons.append(f"The peer line needs {MIN_PEERS} financial peers with P/B and ROE.")
    else:
        view.slope, view.intercept = line
        if view.roe is not None:
            view.line_pb = view.intercept + view.slope * view.roe
            if view.pb is not None:
                view.gap = view.pb - view.line_pb
    if view.pb is None or view.roe is None:
        view.reasons.append("No P/B or ROE in the latest metrics snapshot for this symbol.")
    view.justified_pb = justified_pb(view.roe, view.coe, view.growth)
    if view.coe <= view.growth:
        view.reasons.append("The cost of equity must be above growth for a justified P/B.")
    return view
