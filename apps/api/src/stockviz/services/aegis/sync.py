"""Copy the Aegis feed into StockViz's read-only tables.

One run:

1. Records itself in ``aegis_sync_runs`` (status ``running``).
2. Reads the whole mapping list and replaces ``aegis_mappings`` (audit AG-2:
   the join to StockViz symbols happens locally, so a mapping added later
   applies to documents already held).
3. Pages the feed from the stored cursor. Each page and the cursor that
   follows it commit together, so a run that dies part-way resumes where it
   stopped, and running twice changes nothing: bundles upsert by document id.
4. Marks the run ``succeeded``, or ``failed`` with the error.

A bundle is the document as of its latest signed run, so it replaces the
document's analyses, entities and events. A tombstone (``withdrawal`` set)
deletes the document and everything under it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, delete
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisEvent,
    AegisMapping,
    AegisSyncRun,
    AegisSyncState,
)
from stockviz.services.aegis.client import AegisClient
from stockviz.services.aegis.contract import FeedAnalysis, FeedItem

MAX_ERROR_CHARS = 2000


@dataclass(frozen=True, slots=True)
class SyncResult:
    run_id: int
    pages: int
    upserted: int
    withdrawn: int
    mappings: int


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _required(value: datetime) -> datetime:
    converted = _naive_utc(value)
    assert converted is not None
    return converted


def run_sync(
    engine: Engine,
    client: AegisClient,
    *,
    page_limit: int = 100,
    max_pages: int | None = None,
    now: Callable[[], datetime] = utcnow,
) -> SyncResult:
    """One sync run. Raises after recording a failed run."""
    with Session(engine) as session:
        run = AegisSyncRun(started_at=now())
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.id is not None
        run_id = run.id

    pages = upserted = withdrawn = mappings = 0
    try:
        mappings = _replace_mappings(engine, client)
        cursor = _stored_cursor(engine)
        while max_pages is None or pages < max_pages:
            page = client.feed_page(cursor=cursor, limit=page_limit)
            with Session(engine) as session:
                for item in page.data:
                    if item.withdrawal is not None:
                        withdrawn += _withdraw(session, item.document.document_id)
                    else:
                        _upsert(session, item, now())
                        upserted += 1
                state = session.get(AegisSyncState, 1) or AegisSyncState(id=1)
                state.cursor = page.resume_cursor
                state.updated_at = now()
                session.add(state)
                run = session.get(AegisSyncRun, run_id)
                assert run is not None
                run.pages = pages + 1
                run.documents_upserted = upserted
                run.documents_withdrawn = withdrawn
                run.mappings = mappings
                run.aegis_as_of = _naive_utc(page.as_of)
                session.add(run)
                session.commit()
            pages += 1
            cursor = page.resume_cursor
            if not page.pagination.has_more:
                break
    except Exception as exc:
        _finish(engine, run_id, now(), status="failed", error=f"{exc.__class__.__name__}: {exc}")
        raise
    _finish(engine, run_id, now(), status="succeeded", error=None)
    return SyncResult(
        run_id=run_id, pages=pages, upserted=upserted, withdrawn=withdrawn, mappings=mappings
    )


def _finish(engine: Engine, run_id: int, at: datetime, *, status: str, error: str | None) -> None:
    with Session(engine) as session:
        run = session.get(AegisSyncRun, run_id)
        assert run is not None
        run.status = status
        run.finished_at = at
        run.error = error[:MAX_ERROR_CHARS] if error else None
        session.add(run)
        session.commit()


def _stored_cursor(engine: Engine) -> str | None:
    with Session(engine) as session:
        state = session.get(AegisSyncState, 1)
        return state.cursor if state else None


def _replace_mappings(engine: Engine, client: AegisClient) -> int:
    rows = list(client.mappings())
    with Session(engine) as session:
        session.exec(delete(AegisMapping))  # type: ignore[call-overload]
        for mapping in rows:
            session.add(
                AegisMapping(
                    mapping_id=mapping.mapping_id,
                    entity_id=mapping.entity_id,
                    scheme=mapping.scheme,
                    identifier=mapping.identifier,
                    venue=mapping.venue,
                    created_at=_required(mapping.created_at),
                )
            )
        session.commit()
    return len(rows)


def _delete_children(session: Session, document_id: str) -> None:
    # Explicit, not left to ON DELETE CASCADE, so SQLite (tests) behaves like Postgres.
    for model in (AegisAnalysis, AegisDocumentEntity, AegisEvent):
        session.exec(delete(model).where(model.document_id == document_id))  # type: ignore[call-overload]


def _withdraw(session: Session, document_id: str) -> int:
    existing = session.get(AegisDocument, document_id)
    _delete_children(session, document_id)
    if existing is None:
        return 0
    session.delete(existing)
    session.flush()
    return 1


def _first_output(analysis: FeedAnalysis) -> tuple[str | None, float | None, float | None]:
    output = analysis.outputs[0]
    label = output.get("label")
    score = output.get("score")
    confidence = output.get("confidence")
    return (
        label if isinstance(label, str) else None,
        float(score) if isinstance(score, (int, float)) else None,
        float(confidence) if isinstance(confidence, (int, float)) else None,
    )


def _upsert(session: Session, item: FeedItem, synced_at: datetime) -> None:
    doc = item.document
    latest = item.manifests[-1] if item.manifests else None
    row = session.get(AegisDocument, doc.document_id) or AegisDocument(
        document_id=doc.document_id,
        source_id=doc.source_id,
        source_name=item.source.name,
        title=doc.title,
        first_seen_at=_required(doc.first_seen_at),
        available_at=_required(doc.available_at),
        last_signed_at=_required(doc.last_signed_at),
    )
    row.source_id = doc.source_id
    row.source_name = item.source.name[:512]
    row.source_url = item.source.url
    row.title = doc.title[:512]
    row.url = doc.url
    row.language = doc.language
    row.published_at = _naive_utc(doc.published_at)
    row.first_seen_at = _required(doc.first_seen_at)
    row.available_at = _required(doc.available_at)
    row.last_signed_at = _required(doc.last_signed_at)
    row.revision = doc.revision
    row.manifest_hash = latest.manifest_hash if latest else None
    row.manifest_key_id = latest.key_id if latest else None
    row.synced_at = synced_at
    session.add(row)
    session.flush()

    _delete_children(session, doc.document_id)
    for analysis in item.analyses:
        label, score, confidence = _first_output(analysis)
        session.add(
            AegisAnalysis(
                analysis_id=analysis.analysis_id,
                document_id=doc.document_id,
                analysis_type=analysis.analysis_type,
                provider=analysis.provider,
                model_name=analysis.model_name,
                model_version=analysis.model_version,
                configuration_hash=analysis.configuration_hash,
                available_at=_required(analysis.available_at),
                label=label,
                score=score,
                confidence=confidence,
                outputs=analysis.outputs,
            )
        )
    for entity in {e.entity_id: e for e in item.entities}.values():
        session.add(
            AegisDocumentEntity(
                document_id=doc.document_id,
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name[:512],
                kind=entity.kind,
                resolution_analysis_id=entity.resolution_analysis_id,
                confidence=entity.confidence,
            )
        )
    for event in item.events:
        session.add(
            AegisEvent(
                event_id=event.event_id,
                revision=event.revision,
                document_id=doc.document_id,
                event_type=event.event_type,
                confidence=event.confidence,
                occurred_at=_naive_utc(event.occurred_at),
                available_at=_required(event.available_at),
                evidence_kind=event.evidence_kind,
                analysis_id=event.analysis_id,
            )
        )
    session.flush()
