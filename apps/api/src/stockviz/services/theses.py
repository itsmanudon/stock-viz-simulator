"""Theses (A2.2 table, the M5.6 object): a written view on one instrument with
an optional kill rule in the Rule DSL.

The kill rule must compile when it is saved; nothing judges it yet (the
nightly evaluation is A2.3 / A5). A thesis can be edited while it is
``open``; closing it (``closed`` or ``invalidated``) is final.
"""

from __future__ import annotations

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier
from stockviz.models.setup import Thesis
from stockviz.schemas import ThesisOut

MAX_THESES_PER_USER = 500


def tickers_for(session: Session, instrument_ids: list[int]) -> dict[int, str]:
    """Instrument id -> its current Yahoo ticker."""
    if not instrument_ids:
        return {}
    rows = session.exec(
        select(InstrumentIdentifier.instrument_id, InstrumentIdentifier.value)
        .where(
            col(InstrumentIdentifier.instrument_id).in_(sorted(set(instrument_ids))),
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.valid_to).is_(None),
        )
        .order_by(col(InstrumentIdentifier.valid_from))
    ).all()
    return dict(rows)


def thesis_out(row: Thesis, ticker: str | None, kill: dict | None = None) -> ThesisOut:
    assert row.id is not None
    return ThesisOut(
        **(kill or {}),
        id=row.id,
        ticker=ticker,
        title=row.title,
        body=row.body,
        kill_rule_text=row.kill_rule_text,
        kill_rule_hash=row.kill_rule_hash,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_theses(session: Session, user_id: int, status: str | None = None) -> list[ThesisOut]:
    stmt = select(Thesis).where(col(Thesis.user_id) == user_id)
    if status is not None:
        stmt = stmt.where(col(Thesis.status) == status)
    rows = list(session.exec(stmt.order_by(col(Thesis.updated_at).desc(), col(Thesis.id))).all())
    names = tickers_for(session, [r.instrument_id for r in rows])
    from stockviz.services.thesis_kill import kill_state  # imports this module

    return [thesis_out(r, names.get(r.instrument_id), kill_state(session, r)) for r in rows]


def touch(row: Thesis) -> None:
    row.updated_at = utcnow()


__all__ = ["MAX_THESES_PER_USER", "list_theses", "thesis_out", "tickers_for", "touch"]
