"""The Aegis client and service token, against recorded responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from stockviz.services.aegis.client import AegisClient, AegisError
from stockviz.services.aegis.token import load_signing_key, mint_feed_token

FIXTURES = Path(__file__).parent / "fixtures" / "aegis"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def make_client(handler, sleeps: list[float] | None = None) -> AegisClient:
    waits = sleeps if sleeps is not None else []
    return AegisClient(
        "https://aegis.example.test/",
        token=lambda: "test-token",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def _pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def test_token_carries_the_claims_aegis_validates() -> None:
    key = Ed25519PrivateKey.generate()
    now = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    token = mint_feed_token(
        key,
        key_id="stockviz-sync-2026-11",
        issuer="https://aegis.example.test",
        audience="aegisnews",
        client_id="stockviz-sync",
        now=now,
    )

    header = jwt.get_unverified_header(token)
    assert header == {"alg": "EdDSA", "kid": "stockviz-sync-2026-11", "typ": "at+jwt"}
    claims = jwt.decode(
        token,
        key.public_key(),
        algorithms=["EdDSA"],
        audience="aegisnews",
        issuer="https://aegis.example.test",
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["sub"] == claims["client_id"] == "stockviz-sync"
    assert claims["idtyp"] == "app"
    # feed:read alone: it reaches no route that returns article text.
    assert claims["scope"] == "feed:read"
    assert claims["exp"] - claims["iat"] == 600


def test_signing_key_accepts_a_one_line_env_value() -> None:
    key = Ed25519PrivateKey.generate()
    one_line = _pem(key).strip().replace("\n", "\\n")
    loaded = load_signing_key(one_line)
    assert loaded.public_key().public_bytes_raw() == key.public_key().public_bytes_raw()


def test_signing_key_rejects_a_non_ed25519_key() -> None:
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP256R1())
    pem = other.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    with pytest.raises(ValueError, match="Ed25519"):
        load_signing_key(pem)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def test_feed_page_parses_the_recorded_response() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=recorded("feed-page-1.json"))

    page = make_client(handler).feed_page(cursor="abc", limit=100)

    assert seen == {
        "path": "/api/v1/feed/documents",
        "params": {"limit": "100", "cursor": "abc"},
        "auth": "Bearer test-token",
    }
    assert len(page.data) == 2
    assert page.pagination.has_more is True
    first = page.data[0]
    assert first.document.published_at is None
    sentiment = next(a for a in first.analyses if a.analysis_type == "sentiment")
    assert sentiment.outputs[0]["label"] == "mixed"
    assert first.entities[0].canonical_name == "Apple Inc."


def test_first_page_sends_no_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cursor" not in request.url.params
        return httpx.Response(200, json=recorded("feed-empty.json"))

    page = make_client(handler).feed_page(cursor=None, limit=50)
    assert page.data == []
    assert page.resume_cursor


def test_unknown_fields_are_ignored() -> None:
    """An additive field is not a breaking change under the contract."""
    body = recorded("feed-page-1.json")
    body["new_top_level_field"] = 1
    body["data"][0]["document"]["new_document_field"] = "x"

    page = make_client(lambda _r: httpx.Response(200, json=body)).feed_page(cursor=None, limit=1)
    assert len(page.data) == 2


def test_a_response_off_contract_raises() -> None:
    body = recorded("feed-page-1.json")
    del body["resume_cursor"]
    with pytest.raises(AegisError, match="did not match the contract"):
        make_client(lambda _r: httpx.Response(200, json=body)).feed_page(cursor=None, limit=1)


def test_mappings_follow_the_cursor_across_pages() -> None:
    cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        name = "mappings-page-2.json" if cursor else "mappings-page-1.json"
        return httpx.Response(200, json=recorded(name))

    rows = list(make_client(handler).mappings())
    assert [r.identifier for r in rows] == [
        "AAPL",
        "stockviz:AAPL",
        "RELIANCE",
        "stockviz:RELIANCE.NS",
    ]
    assert cursors == [None, "map_00000000-0000-5000-8000-000000000002"]


def test_retries_a_waking_service_then_succeeds() -> None:
    """Aegis sleeps when idle: a 503 then a connection error, then the page."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        if calls["n"] == 2:
            raise httpx.ConnectError("waking")
        return httpx.Response(200, json=recorded("feed-empty.json"))

    sleeps: list[float] = []
    make_client(handler, sleeps).feed_page(cursor=None, limit=1)
    assert calls["n"] == 3
    assert sleeps == [2.0, 5.0]


def test_rate_limit_honours_retry_after_with_a_cap() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(200, json=recorded("feed-empty.json"))

    sleeps: list[float] = []
    make_client(handler, sleeps).feed_page(cursor=None, limit=1)
    assert sleeps == [60.0]


def test_gives_up_after_the_retries() -> None:
    sleeps: list[float] = []
    with pytest.raises(AegisError) as caught:
        make_client(lambda _r: httpx.Response(502), sleeps).feed_page(cursor=None, limit=1)
    assert caught.value.status == 502
    assert len(sleeps) == 3


def test_an_auth_error_is_not_retried_and_keeps_the_aegis_code() -> None:
    sleeps: list[float] = []
    body = {"error": {"code": "FORBIDDEN", "message": "Missing scope", "request_id": "r"}}
    with pytest.raises(AegisError) as caught:
        make_client(lambda _r: httpx.Response(403, json=body), sleeps).feed_page(
            cursor=None, limit=1
        )
    assert caught.value.code == "FORBIDDEN"
    assert "Missing scope" in str(caught.value)
    assert sleeps == []
