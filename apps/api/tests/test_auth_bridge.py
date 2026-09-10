"""Security properties of the web -> api auth bridge.

Router tests exercise the happy path and the two obvious rejections (no
header, garbage string). The bridge's actual security guarantees had no
coverage: a token signed with the wrong secret, an expired token, and a
token whose algorithm the verifier is not supposed to accept.

Those three are the reasons the bridge replaced the old
``X-Internal-Token`` + ``X-User-Id`` header pair. Without tests, a change
that dropped signature verification, expiry checking, or the algorithm
allow-list would leave every other test in the suite passing while
letting anyone mint a token for any user.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
ENDPOINT = "/v1/portfolio"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session, email: str) -> int:
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _unsigned(claims: dict[str, object]) -> str:
    """Hand-build an ``alg: none`` JWT — python-jose refuses to encode one."""

    def seg(obj: dict[str, object]) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg(claims)}."


def _claims(user_id: int = 1, **overrides: object) -> dict[str, object]:
    """The claim set the Next.js server mints (see apps/web/lib/api/server.ts)."""
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=60)).timestamp()),
    }
    claims.update(overrides)
    return claims


def test_rejects_token_signed_with_a_different_secret(client: TestClient) -> None:
    """The whole point of the bridge: `sub` is signed, so it cannot be forged."""
    forged = jose_jwt.encode(_claims(user_id=1), "not-the-shared-secret", algorithm="HS256")
    assert client.get(ENDPOINT, headers=_bearer(forged)).status_code == 401


def test_rejects_expired_token(client: TestClient) -> None:
    """The 60s expiry bounds the replay window and must actually be enforced."""
    expired = jose_jwt.encode(
        _claims(exp=int((datetime.now(UTC) - timedelta(seconds=30)).timestamp())),
        SECRET,
        algorithm="HS256",
    )
    assert client.get(ENDPOINT, headers=_bearer(expired)).status_code == 401


def test_accepts_a_token_that_has_not_yet_expired(session: Session, client: TestClient) -> None:
    """Control for the expiry test — the same claim shape must still work."""
    user_id = _make_user(session, "live@example.com")
    valid = jose_jwt.encode(_claims(user_id), SECRET, algorithm="HS256")
    assert client.get(ENDPOINT, headers=_bearer(valid)).status_code == 200


def test_rejects_unsigned_token(client: TestClient) -> None:
    """`alg: none` is the classic JWT bypass; `algorithms=["HS256"]` blocks it."""
    assert client.get(ENDPOINT, headers=_bearer(_unsigned(_claims()))).status_code == 401


def test_rejects_token_missing_sub(client: TestClient) -> None:
    claims = _claims()
    del claims["sub"]
    token = jose_jwt.encode(claims, SECRET, algorithm="HS256")
    assert client.get(ENDPOINT, headers=_bearer(token)).status_code == 401


def test_rejects_non_numeric_sub(client: TestClient) -> None:
    """`sub` is cast with int(); a non-numeric claim must 401, not 500."""
    token = jose_jwt.encode(_claims(sub="not-an-integer"), SECRET, algorithm="HS256")
    assert client.get(ENDPOINT, headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "bearer lowercase-scheme",
    ],
)
def test_rejects_malformed_authorization_header(client: TestClient, header: str) -> None:
    assert client.get(ENDPOINT, headers={"Authorization": header}).status_code == 401


def test_sub_selects_the_acting_user(session: Session, client: TestClient) -> None:
    """Two different `sub` values must bootstrap two distinct portfolios."""
    alice = _make_user(session, "alice@example.com")
    bob = _make_user(session, "bob@example.com")

    first = client.get(ENDPOINT, headers=_bearer(jose_jwt.encode(_claims(alice), SECRET, "HS256")))
    second = client.get(ENDPOINT, headers=_bearer(jose_jwt.encode(_claims(bob), SECRET, "HS256")))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["portfolio_id"] != second.json()["portfolio_id"]
