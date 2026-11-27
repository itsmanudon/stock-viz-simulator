"""`GET /v1/brief` (A9.12, M11.6): the signed-in user's morning brief.

What changed for the symbols they hold or watch: the last stored daily move
with its dates, alerts fired in the last 24 hours, earnings in the next 7
days, documents made public in the last 7 days, and counts of open plans and
pending orders. Read only; end-of-day data, never a live quote.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import (
    BriefAlertOut,
    BriefDocumentOut,
    BriefEarningsOut,
    BriefMoveOut,
    MorningBriefOut,
)
from stockviz.services.brief import morning_brief

router = APIRouter(tags=["brief"])

NOTE = (
    "Moves compare each symbol's last two stored daily closes, dated; StockViz is end of day, "
    "so a move is not today's unless its date is today."
)


@router.get("/v1/brief", response_model=MorningBriefOut)
def get_brief(
    user_id: UserIdDep, session: Annotated[Session, Depends(get_session)]
) -> MorningBriefOut:
    b = morning_brief(session, user_id)
    return MorningBriefOut(
        generated_at=b.generated_at,
        symbols=b.symbols,
        moves=[BriefMoveOut(**m.__dict__) for m in b.moves],
        alerts=[
            BriefAlertOut(title=n.title, body=n.body, link=n.link, created_at=n.created_at)
            for n in b.alerts
        ],
        earnings=[BriefEarningsOut(ticker=e.ticker, event_date=e.event_date) for e in b.earnings],
        documents=[
            BriefDocumentOut(
                id=d.id or 0, ticker=t, title=d.title, kind=d.kind, available_at=d.available_at
            )
            for d, t in b.documents
        ],
        open_plans=b.open_plans,
        pending_orders=b.pending_orders,
        note=NOTE,
    )
