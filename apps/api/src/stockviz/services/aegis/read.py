"""Reads over the copied Aegis tables.

Documents link to StockViz symbols through the local join
document -> resolved entity -> Aegis mapping ``provider_id`` ``stockviz:<ticker>``.
Because the join runs at read time, a mapping seeded after a document was
synced still links it.

Point in time: ``as_of`` bounds on the document's ``available_at``, never on
``published_at`` (audit AG-12).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from stockviz.models import AegisDocument, AegisDocumentEntity, AegisMapping

STOCKVIZ_SCHEME = "provider_id"


def stockviz_identifier(ticker: str) -> str:
    return f"stockviz:{ticker.strip().upper()}"


def documents_for_ticker(
    session: Session, ticker: str, *, as_of: datetime | None = None, limit: int = 50
) -> list[AegisDocument]:
    """Newest-available first. Each document once, however many entities link it."""
    linked = (
        select(AegisDocumentEntity.document_id)
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(
            AegisMapping.scheme == STOCKVIZ_SCHEME,
            AegisMapping.identifier == stockviz_identifier(ticker),
        )
    )
    stmt = select(AegisDocument).where(col(AegisDocument.document_id).in_(linked))
    if as_of is not None:
        stmt = stmt.where(AegisDocument.available_at <= as_of)
    stmt = stmt.order_by(
        col(AegisDocument.available_at).desc(), col(AegisDocument.document_id)
    ).limit(limit)
    return list(session.exec(stmt).all())
