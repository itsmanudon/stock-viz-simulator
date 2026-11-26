"""Feed status: what each US feed can do on this server (A6.3, beside A5.7's brokers).

States:

- ``not_configured``: the provider's key env var is blank.
- ``configured``: the key is set and no backfill has run yet (or Finnhub,
  which has no backfill until A6.6).
- ``ok``: the newest ``intraday-backfill --apply`` run succeeded.
- ``error``: the newest run failed within ``OFFLINE_WINDOW``; ``last_error``
  is its fixed summary (e.g. "Alpaca: auth error on 3 symbol(s)"), never a
  key or the provider's text.

Streams (A6.5, :func:`stream_statuses`): one row per stream the worker has
run (``feed_streams``): ``streaming``, ``closed`` or ``error``. A
``streaming`` row not updated for :data:`STREAM_STALE` is reported
``closed`` (the worker stopped without saying so). ``live`` is false for the
``simulated`` replay, which is never called live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import FeedStream, JobRun
from stockviz.services.brokers import FEED_BACKFILL_JOBS, OFFLINE_WINDOW
from stockviz.services.feeds.base import Capabilities
from stockviz.services.feeds.registry import FEED_CLASSES, KEY_ENV_VARS, build_feed
from stockviz.settings import Settings

FeedState = Literal["not_configured", "configured", "ok", "error"]


@dataclass(frozen=True)
class FeedStatus:
    provider: str
    label: str
    configured: bool
    state: FeedState
    capabilities: Capabilities
    key_env_vars: tuple[str, ...]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None


def _last(session: Session, job: str, status: str) -> JobRun | None:
    return session.exec(
        select(JobRun)
        .where(JobRun.job == job, JobRun.status == status)
        .order_by(col(JobRun.finished_at).desc(), col(JobRun.id).desc())
        .limit(1)
    ).first()


def feed_statuses(
    session: Session, settings: Settings, *, now: datetime | None = None
) -> list[FeedStatus]:
    moment = now or utcnow()
    out: list[FeedStatus] = []
    for name in FEED_CLASSES:
        feed = build_feed(name, settings)
        job = FEED_BACKFILL_JOBS.get(name)
        ok = _last(session, job, "succeeded") if job else None
        bad = _last(session, job, "failed") if job else None
        ok_at = ok.finished_at if ok else None
        bad_at = bad.finished_at if bad else None
        state: FeedState
        if not feed.configured:
            state = "not_configured"
        elif (
            bad_at is not None
            and (ok_at is None or bad_at > ok_at)
            and moment - bad_at <= OFFLINE_WINDOW
        ):
            state = "error"
        elif ok_at is not None:
            state = "ok"
        else:
            state = "configured"
        out.append(
            FeedStatus(
                provider=name,
                label=feed.label,
                configured=feed.configured,
                state=state,
                capabilities=feed.capabilities,
                key_env_vars=KEY_ENV_VARS[name],
                last_success_at=ok_at,
                last_failure_at=bad_at,
                last_error=bad.error if bad is not None and state == "error" else None,
            )
        )
    return out


STREAM_STALE = timedelta(minutes=5)


@dataclass(frozen=True)
class StreamStatus:
    name: str
    label: str
    live: bool
    state: str
    stale: bool
    symbols: tuple[str, ...]
    started_at: datetime
    stopped_at: datetime | None
    last_tick_at: datetime | None
    last_bar_at: datetime | None
    bars_written: int
    alerts_fired: int
    error: str | None


def stream_statuses(session: Session, *, now: datetime | None = None) -> list[StreamStatus]:
    moment = now or utcnow()
    out: list[StreamStatus] = []
    for row in session.exec(select(FeedStream).order_by(col(FeedStream.name))).all():
        stale = row.state == "streaming" and moment - row.updated_at > STREAM_STALE
        out.append(
            StreamStatus(
                name=row.name,
                label=row.label,
                live=row.name != "simulated",
                state="closed" if stale else row.state,
                stale=stale,
                symbols=tuple(row.symbols or ()),
                started_at=row.started_at,
                stopped_at=row.stopped_at,
                last_tick_at=row.last_tick_at,
                last_bar_at=row.last_bar_at,
                bars_written=row.bars_written,
                alerts_fired=row.alerts_fired,
                error=row.error,
            )
        )
    return out
