"""The web server's server-side calls skip the public limiter (audit RS-6).

On Railway every server-rendered page reached the API from the web container
with no forwarded address, so all visitors shared one bucket. The web server
now proves itself with ``X-StockViz-Web`` and limits visitors on its side.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from stockviz.limiter import WEB_SERVER_HEADER, is_web_server, limiter, web_server_key
from stockviz.settings import get_settings

# Built once: the shared limiter keeps every limit registered on it, so a
# per-test app would stack one "2/minute" per test on the same endpoint name.
_app = FastAPI()
_app.state.limiter = limiter
_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


@_app.get("/probe")
@limiter.limit("2/minute")
def _probe(request: Request) -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture
def client() -> Iterator[TestClient]:
    saved = limiter.enabled
    limiter.enabled = True
    try:
        with TestClient(_app) as c:
            yield c
    finally:
        limiter.enabled = saved


def _key() -> str:
    return web_server_key(get_settings().internal_api_token)


def _visitor(address: str, **extra: str) -> dict[str, str]:
    # One address per test: the limiter's memory storage outlives a test.
    return {"x-forwarded-for": address, **extra}


def test_a_visitor_burst_is_limited(client: TestClient) -> None:
    codes = [client.get("/probe", headers=_visitor("192.0.2.1")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_the_web_server_is_not_limited(client: TestClient) -> None:
    headers = _visitor("192.0.2.2", **{WEB_SERVER_HEADER: _key()})
    codes = [client.get("/probe", headers=headers).status_code for _ in range(5)]
    assert codes == [200] * 5


def test_a_wrong_key_gets_no_exemption(client: TestClient) -> None:
    headers = _visitor("192.0.2.3", **{WEB_SERVER_HEADER: "0" * 64})
    codes = [client.get("/probe", headers=headers).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_web_server_traffic_does_not_spend_a_visitor_bucket(client: TestClient) -> None:
    for _ in range(5):
        client.get("/probe", headers=_visitor("192.0.2.4", **{WEB_SERVER_HEADER: _key()}))
    assert client.get("/probe", headers=_visitor("192.0.2.4")).status_code == 200


def test_key_is_bound_to_the_secret() -> None:
    assert web_server_key("a") != web_server_key("b")
    assert len(web_server_key("a")) == 64


def test_missing_header_is_not_the_web_server() -> None:
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    assert is_web_server(request) is False
