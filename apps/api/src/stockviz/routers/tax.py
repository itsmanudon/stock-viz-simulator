"""`GET /v1/tax/india` (A7.12, M10.7): an INR book's FY capital gains estimate.

Authed; another user's book is 404 (``resolve_book``). Read only.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import (
    IndiaTaxOut,
    TaxComputationOut,
    TaxIntradayOut,
    TaxOpenLotOut,
    TaxRealisedOut,
    TaxRulesOut,
    TaxSourceOut,
    TaxUnmatchedOut,
)
from stockviz.services.tax import lots as lot_rules
from stockviz.services.tax.report import TaxNotAvailable, build_report
from stockviz.services.tax.rules import ESTIMATE_NOTE, FY_RULES, fy_of
from stockviz.services.trading.books import resolve_book

router = APIRouter(prefix="/v1/tax", tags=["tax"])

SessionDep = Annotated[Session, Depends(get_session)]


def _method() -> list[str]:
    doc = (lot_rules.__doc__ or "").split("\n\n", 1)[-1]
    return [" ".join(part.split()) for part in doc.split("- **") if part.strip()]


@router.get("/india", response_model=IndiaTaxOut)
def india_tax(
    session: SessionDep,
    user_id: UserIdDep,
    book: Annotated[int | None, Query(ge=1)] = None,
    fy: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    surcharge: Annotated[Decimal, Query(ge=0, le=0.37)] = Decimal(0),
) -> IndiaTaxOut:
    chosen = resolve_book(session, user_id, book)
    year = fy or fy_of(date.today())
    if year not in FY_RULES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"FY {year}: covers {', '.join(FY_RULES)} only"
        )
    try:
        report = build_report(session, chosen, year, surcharge_rate=surcharge)
    except TaxNotAvailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    r = report.rules
    in_fy = [x for x in report.book.realised if r.start <= x.sold <= r.end]
    days = [x for x in report.book.intraday if r.start <= x.day <= r.end]
    assert chosen.id is not None
    return IndiaTaxOut(
        book_id=chosen.id,
        fy=year,
        as_of=report.as_of,
        surcharge_rate=min(surcharge, r.surcharge_cap),
        rules=TaxRulesOut(
            fy=r.fy,
            start=r.start,
            end=r.end,
            act=r.act,
            stcg_section=r.stcg_section,
            ltcg_section=r.ltcg_section,
            stcg_rate=r.stcg_rate,
            ltcg_rate=r.ltcg_rate,
            ltcg_exemption=r.ltcg_exemption,
            cess_rate=r.cess_rate,
            surcharge_cap=r.surcharge_cap,
            long_term_after_months=r.long_term_after_months,
            sources=[TaxSourceOut(**asdict(s)) for s in r.sources],
        ),
        computation=TaxComputationOut(**asdict(report.fy)),
        realised=[TaxRealisedOut(**asdict(x)) for x in in_fy],
        intraday=[TaxIntradayOut(**asdict(x)) for x in days],
        open_lots=[TaxOpenLotOut(**asdict(x)) for x in report.open_lots],
        unmatched=[
            TaxUnmatchedOut(ticker=t, day=d, quantity=q)
            for t, d, q in report.book.unmatched
            if r.start <= d <= r.end
        ],
        skipped_tickers=report.skipped_tickers,
        method=_method(),
        estimate_note=ESTIMATE_NOTE,
    )
