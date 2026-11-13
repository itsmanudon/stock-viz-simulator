"""Phase 6.6 RS-9: the cron's call to the web cache route."""

from __future__ import annotations

import httpx
import pytest

from stockviz import cli

# Same value as the web's revalidateKey("test-secret")
# (apps/web/tests/unit/revalidate-route.test.ts).
KEY = "d5a8aaaaca52b715f19a726eef34f3409b1a8f3cf8efc86156a42b71d398eb85"


def test_key_matches_the_web() -> None:
    assert cli.revalidate_key("test-secret") == KEY


@pytest.fixture(autouse=True)
def _fresh_settings():
    # These tests change INTERNAL_API_TOKEN. Clear the cached settings after
    # each, or every later test signs with the real token while the app still
    # holds "test-secret", and authenticated tests fail with 401.
    yield
    cli.get_settings.cache_clear()


def _settings(monkeypatch, url: str) -> None:
    monkeypatch.setenv("WEB_REVALIDATE_URL", url)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-secret")
    cli.get_settings.cache_clear()


def test_unset_url_skips(monkeypatch) -> None:
    _settings(monkeypatch, "")
    assert cli.main(["revalidate-web"]) == 2


def test_sent_with_the_key_and_outcomes(monkeypatch) -> None:
    _settings(monkeypatch, "https://web.example/api/revalidate")
    sent: dict = {}

    def post(url, headers, timeout, status=200):
        sent.update(url=url, headers=headers)
        return httpx.Response(status, text='{"revalidated":["bars"]}')

    monkeypatch.setattr(httpx, "post", post)
    assert cli.main(["revalidate-web"]) == 0
    assert sent["headers"]["X-StockViz-Revalidate"] == cli.revalidate_key("test-secret")

    monkeypatch.setattr(httpx, "post", lambda url, headers, timeout: httpx.Response(401))
    assert cli.main(["revalidate-web"]) == 1  # a misconfigured key fails the night

    def unreachable(url, headers, timeout):
        raise httpx.ConnectError("asleep")

    monkeypatch.setattr(httpx, "post", unreachable)
    assert cli.main(["revalidate-web"]) == 0  # a sleeping web has no cache to drop
