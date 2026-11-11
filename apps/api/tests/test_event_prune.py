"""Retention for the outbox and inbox tables (audit OP-11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from stockviz import cli
from stockviz.events.prune import prune_events
from stockviz.models.events import ConsumerInbox, OutboxEvent

NOW = datetime(2026, 11, 11, 22, 0)
OLD = NOW - timedelta(days=45)
RECENT = NOW - timedelta(days=3)


def _outbox(session: Session, *, created_at: datetime, published_at: datetime | None) -> None:
    session.add(
        OutboxEvent(
            event_type="news.article.ingested",
            aggregate_type="news_article",
            aggregate_id="1",
            topic="stockviz.news.v1",
            partition_key="AAPL",
            payload={},
            occurred_at=created_at,
            created_at=created_at,
            published_at=published_at,
        )
    )


def _inbox(session: Session, *, processed_at: datetime) -> None:
    session.add(
        ConsumerInbox(consumer_name="news-ingest", event_id=uuid.uuid4(), processed_at=processed_at)
    )


def _seed(session: Session) -> None:
    _outbox(session, created_at=OLD, published_at=OLD)  # old, published: pruned
    _outbox(session, created_at=OLD, published_at=RECENT)  # published lately: kept
    _outbox(session, created_at=OLD, published_at=None)  # old, never sent
    _outbox(session, created_at=RECENT, published_at=None)  # waiting to be sent
    _inbox(session, processed_at=OLD)
    _inbox(session, processed_at=RECENT)
    session.commit()


def test_prune_keeps_unpublished_rows_by_default(session: Session) -> None:
    _seed(session)

    result = prune_events(session, now=NOW)
    session.commit()

    assert (result.published, result.unpublished, result.inbox) == (1, 0, 1)
    remaining = session.exec(select(OutboxEvent)).all()
    assert len(remaining) == 3
    assert sum(1 for row in remaining if row.published_at is None) == 2
    assert len(session.exec(select(ConsumerInbox)).all()) == 1


def test_prune_can_clear_old_unpublished_rows(session: Session) -> None:
    """Only where no publisher runs: the Railway cron passes the flag."""
    _seed(session)

    result = prune_events(session, now=NOW, include_unpublished=True)
    session.commit()

    assert (result.published, result.unpublished, result.inbox) == (1, 1, 1)
    remaining = session.exec(select(OutboxEvent)).all()
    assert {row.created_at for row in remaining if row.published_at is None} == {RECENT}


def test_prune_rejects_a_zero_retention(session: Session) -> None:
    with pytest.raises(ValueError):
        prune_events(session, now=NOW, retention_days=0)


def test_cli_prune_events(engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: NOW)
    with Session(engine) as session:
        _seed(session)

    assert cli.main(["prune-events", "--include-unpublished"]) == 0

    out = capsys.readouterr().out
    assert "1 published outbox, 1 unpublished outbox, 1 inbox" in out
    with Session(engine) as session:
        assert len(session.exec(select(OutboxEvent)).all()) == 2
