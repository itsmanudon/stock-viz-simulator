"""A9.7 (M1.10, M3.5): FRED macro series, the sync, the view and the routes.

Every FRED answer here is hand-written in the documented shape; no test
reaches FRED.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import MacroObservation, MacroSeries
from stockviz.services.feeds.base import FeedProviderError, RateLimitSpec
from stockviz.services.feeds.ratelimit import RateLimiter
from stockviz.services.macro import view
from stockviz.services.macro.catalogue import BY_ID, CATALOGUE, SPREADS
from stockviz.services.macro.fred import FredClient
from stockviz.services.macro.sync import sync_catalogue

KEY = "test-fred-key-0123456789"


class FakeFred:
    """Answers ``series`` and ``series/observations`` from a dict of series."""

    def __init__(self, data: dict[str, list[tuple[str, str]]], status: int = 200) -> None:
        self.data = data
        self.status = status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        self.calls.append((url, dict(params)))
        request = httpx.Request("GET", url, params=params)
        if self.status != 200:
            return httpx.Response(self.status, json={"error_message": "bad"}, request=request)
        sid = params["series_id"]
        if sid not in self.data:
            return httpx.Response(400, json={"error_message": "no series"}, request=request)
        if url.endswith("/series"):
            body: dict[str, Any] = {
                "seriess": [
                    {
                        "id": sid,
                        "title": f"Title {sid}",
                        "units": "Percent",
                        "frequency": "Daily",
                        "observation_start": "2000-01-03",
                        "observation_end": self.data[sid][-1][0] if self.data[sid] else None,
                        "last_updated": "2026-11-26 15:01:02-06",
                    }
                ]
            }
        else:
            start = params["observation_start"]
            body = {
                "observations": [{"date": d, "value": v} for d, v in self.data[sid] if d >= start]
            }
        return httpx.Response(200, json=body, request=request)


def _client(fake: FakeFred) -> FredClient:
    limiter = RateLimiter.from_specs([RateLimitSpec(calls=1000, per_seconds=1)])
    return FredClient(KEY, get=fake, limiter=limiter)


def _daily(start: date, values: list[float]) -> list[tuple[str, str]]:
    return [((start + timedelta(days=i)).isoformat(), str(v)) for i, v in enumerate(values)]


# --- client ---------------------------------------------------------------


def test_client_parses_metadata_and_missing_values() -> None:
    fake = FakeFred({"DGS10": [("2026-01-02", "4.10"), ("2026-01-05", "."), ("2026-01-06", "4.2")]})
    client = _client(fake)
    meta = client.series("DGS10")
    assert meta.title == "Title DGS10" and meta.frequency == "Daily"
    assert meta.observation_start == date(2000, 1, 3)
    rows = client.observations("DGS10", date(2026, 1, 1))
    assert rows == [
        (date(2026, 1, 2), Decimal("4.10")),
        (date(2026, 1, 5), None),
        (date(2026, 1, 6), Decimal("4.2")),
    ]
    url, params = fake.calls[-1]
    assert url == "https://api.stlouisfed.org/fred/series/observations"
    assert params["file_type"] == "json" and params["observation_start"] == "2026-01-01"


def test_errors_never_carry_the_key(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client = _client(FakeFred({}, status=400))
    with pytest.raises(FeedProviderError) as err:
        client.series("DGS10")
    assert KEY not in str(err.value)
    assert KEY not in caplog.text


def test_a_value_that_is_not_a_number_is_a_provider_error() -> None:
    client = _client(FakeFred({"X": [("2026-01-02", "abc")]}))
    with pytest.raises(FeedProviderError):
        client.observations("X", date(2026, 1, 1))


# --- sync -----------------------------------------------------------------


def test_sync_stores_then_reruns_idempotently_and_takes_revisions(session: Session) -> None:
    data = {"DGS10": _daily(date(2026, 1, 1), [4.0, 4.1, 4.2])}
    fake = FakeFred(data)
    entries = [BY_ID["DGS10"]]
    report = sync_catalogue(session, _client(fake), entries)
    assert report.written == 3 and not report.failed
    meta = session.get(MacroSeries, "DGS10")
    assert meta is not None and meta.title == "Title DGS10" and meta.fetched_at is not None

    # A rerun asks from REVISION_DAYS before the newest date and rewrites, never duplicates.
    data["DGS10"][1] = ("2026-01-02", "4.15")
    data["DGS10"].append(("2026-01-04", "4.3"))
    sync_catalogue(session, _client(fake), entries)
    rows = session.exec(select(MacroObservation).where(MacroObservation.series_id == "DGS10")).all()
    values = {r.obs_date: r.value for r in rows}
    assert len(rows) == 4
    assert values[date(2026, 1, 2)] == Decimal("4.15")
    assert fake.calls[-1][1]["observation_start"] == "2024-11-29"


def test_a_failing_series_skips_while_auth_stops_the_run(session: Session) -> None:
    fake = FakeFred({"DGS2": _daily(date(2026, 1, 1), [4.0])})
    report = sync_catalogue(session, _client(fake), [BY_ID["DGS10"], BY_ID["DGS2"]])
    assert [r.series_id for r in report.failed] == ["DGS10"]
    assert report.results[1].written == 1 and report.stopped is None

    denied = sync_catalogue(
        session, _client(FakeFred({}, status=403)), [BY_ID["DGS10"], BY_ID["DGS2"]]
    )
    assert denied.stopped == "FRED auth error" and len(denied.results) == 1


# --- view -----------------------------------------------------------------


def test_changes_compare_with_the_value_on_or_before_a_year_earlier() -> None:
    pts = [view.Point(date(2025, 1, 1), 3.0), view.Point(date(2025, 6, 1), 3.5)]
    pts.append(view.Point(date(2026, 1, 3), 4.0))
    assert view.value_on_or_before(pts, date(2025, 1, 3)) == pts[0]
    assert view.value_on_or_before(pts, date(2024, 12, 31)) is None


def test_stale_depends_on_frequency() -> None:
    assert view.stale_after_days("Daily") == 10
    assert view.stale_after_days("Monthly") == 75
    assert view.stale_after_days("Quarterly") == 160
    assert view.stale_after_days("Weekly, Ending Saturday") == 21


def test_thin_keeps_the_last_point() -> None:
    pts = [view.Point(date(2020, 1, 1) + timedelta(days=i), float(i)) for i in range(1000)]
    out = view.thin(pts, 50)
    assert len(out) == 50 and out[-1] == pts[-1] and out[0] == pts[0]


def test_spread_uses_b_as_of_a_s_date_at_most_a_week_old() -> None:
    a = [view.Point(date(2026, 1, d), float(d)) for d in (5, 6, 20)]
    b = [view.Point(date(2026, 1, 2), 1.0), view.Point(date(2026, 1, 6), 2.0)]
    out = view.spread_points(a, b)
    # 5 Jan uses 2 Jan's b; 6 Jan its own; 20 Jan's b is 14 days old: left out.
    assert out == [view.Point(date(2026, 1, 5), 4.0), view.Point(date(2026, 1, 6), 4.0)]


def test_every_spread_names_catalogue_series() -> None:
    for sp in SPREADS:
        assert sp.a in BY_ID and sp.b in BY_ID
    assert len({s.series_id for s in CATALOGUE}) == len(CATALOGUE)


# --- routes ---------------------------------------------------------------


def _store(session: Session, sid: str, start: date, values: list[float | None]) -> None:
    session.add(
        MacroSeries(
            series_id=sid,
            title=f"Title {sid}",
            units="Percent",
            frequency="Daily",
            fetched_at=datetime(2026, 11, 27, 9, 0),
        )
    )
    for i, v in enumerate(values):
        session.add(
            MacroObservation(
                series_id=sid,
                obs_date=start + timedelta(days=i),
                value=Decimal(str(v)) if v is not None else None,
            )
        )
    session.commit()


def test_overview_route(client: TestClient, session: Session, monkeypatch) -> None:
    today = date(2026, 11, 27)
    monkeypatch.setattr("stockviz.routers.macro.utcnow", lambda: datetime(2026, 11, 27, 12))
    start = today - timedelta(days=400)
    n = 400
    _store(session, "DGS10", start, [4.0 + 0.001 * i for i in range(n)])
    _store(session, "DGS2", start, [3.0] * n)
    body = client.get("/v1/macro").json()
    by_id = {s["series_id"]: s for s in body["series"]}
    assert set(by_id) == {s.series_id for s in CATALOGUE}
    ten = by_id["DGS10"]
    assert ten["fetched"] and not ten["stale"]
    assert ten["latest"]["value"] == pytest.approx(4.399)
    assert ten["change_year"] == pytest.approx(0.365, abs=1e-6)
    assert ten["source_url"].endswith("/DGS10")
    assert not by_id["CPIAUCSL"]["fetched"] and by_id["CPIAUCSL"]["stale"]
    assert by_id["VIXCLS"]["third_party"] is True
    spreads = {s["key"]: s for s in body["spreads"]}
    assert spreads["us_10y_2y"]["latest"]["value"] == pytest.approx(1.399)
    assert spreads["brent_wti"]["points"] == [] and "DCOILBRENTEU" in spreads["brent_wti"]["reason"]
    assert body["last_fetched_at"].startswith("2026-11-27")


def test_series_route_and_unknown_series(client: TestClient, session: Session) -> None:
    _store(session, "DGS10", date(2026, 1, 1), [4.0, None, 4.2])
    body = client.get("/v1/macro/dgs10?from=2026-01-02").json()
    assert body["series"]["series_id"] == "DGS10"
    assert body["observations"] == [
        {"day": "2026-01-02", "value": None},
        {"day": "2026-01-03", "value": 4.2},
    ]
    assert client.get("/v1/macro/NOPE").status_code == 404


# --- CLI ------------------------------------------------------------------


def test_cli_without_a_key_exits_2(monkeypatch, capsys) -> None:
    from stockviz.settings import get_settings

    monkeypatch.setenv("FRED_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert cli.main(["macro-sync"]) == 2
    finally:
        get_settings.cache_clear()
    assert "FRED_API_KEY" in capsys.readouterr().err


def test_cli_refuses_unknown_series(monkeypatch, capsys) -> None:
    from stockviz.settings import get_settings

    monkeypatch.setenv("FRED_API_KEY", KEY)
    get_settings.cache_clear()
    try:
        assert cli.main(["macro-sync", "--series", "NOPE"]) == 1
    finally:
        get_settings.cache_clear()
    assert "NOPE" in capsys.readouterr().err
    assert "macro-sync" in cli.RECORDED_JOBS
