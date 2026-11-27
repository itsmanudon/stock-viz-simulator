"""Fetch the catalogue's series from FRED into ``macro_series`` and
``macro_observations`` (A9.7).

The first fetch of a series reads from ``DEFAULT_START``. Later fetches read
from ``REVISION_DAYS`` before the newest stored date, because FRED revises
recent values (payrolls, GDP), so a rerun updates them and adds new dates.
Upserts on (series, date): a rerun with nothing new writes the same values.
One commit per series, so a failing series leaves the others stored.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from stockviz.models import MacroObservation, MacroSeries
from stockviz.services.feeds.base import FeedAuthError, FeedError, FeedRateError
from stockviz.services.macro.catalogue import CATALOGUE, CatalogueSeries
from stockviz.services.macro.fred import FredClient

logger = logging.getLogger(__name__)

DEFAULT_START = date(2000, 1, 1)
REVISION_DAYS = 400
CHUNK = 2000


@dataclass
class SeriesResult:
    series_id: str
    written: int = 0
    error: str | None = None


@dataclass
class SyncReport:
    results: list[SeriesResult] = field(default_factory=list)
    stopped: str | None = None

    @property
    def failed(self) -> list[SeriesResult]:
        return [r for r in self.results if r.error]

    @property
    def written(self) -> int:
        return sum(r.written for r in self.results)


def _newest(session: Session, series_id: str) -> date | None:
    return session.exec(
        select(func.max(MacroObservation.obs_date)).where(MacroObservation.series_id == series_id)
    ).one()


def _upsert(session: Session, series_id: str, rows: list[tuple[date, Decimal | None]]) -> int:
    dialect = session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    for i in range(0, len(rows), CHUNK):
        values = [
            {"series_id": series_id, "obs_date": d, "value": v} for d, v in rows[i : i + CHUNK]
        ]
        stmt = insert(MacroObservation).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["series_id", "obs_date"], set_={"value": stmt.excluded.value}
        )
        session.exec(stmt)  # type: ignore[arg-type]
    return len(rows)


def sync_one(session: Session, client: FredClient, entry: CatalogueSeries) -> int:
    meta = client.series(entry.series_id)
    newest = _newest(session, entry.series_id)
    start = DEFAULT_START if newest is None else newest - timedelta(days=REVISION_DAYS)
    rows = client.observations(entry.series_id, max(start, DEFAULT_START))
    stored = session.get(MacroSeries, entry.series_id) or MacroSeries(
        series_id=entry.series_id, title=meta.title
    )
    stored.provider = "fred"
    stored.title = meta.title
    stored.units = meta.units
    stored.frequency = meta.frequency
    stored.observation_start = meta.observation_start
    stored.observation_end = meta.observation_end
    stored.provider_updated = meta.last_updated
    stored.fetched_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(stored)
    session.flush()
    written = _upsert(session, entry.series_id, rows)
    session.commit()
    return written


def sync_catalogue(
    session: Session, client: FredClient, entries: Iterable[CatalogueSeries] = CATALOGUE
) -> SyncReport:
    """Fetch each series; an auth or rate error stops the run, others skip one."""
    report = SyncReport()
    for entry in entries:
        result = SeriesResult(entry.series_id)
        report.results.append(result)
        try:
            result.written = sync_one(session, client, entry)
        except (FeedAuthError, FeedRateError) as exc:
            session.rollback()
            result.error = exc.summary
            report.stopped = exc.summary
            break
        except FeedError as exc:
            session.rollback()
            result.error = exc.summary
            logger.warning("macro-sync: %s failed (%s)", entry.series_id, exc.summary)
    return report
