"""Mint the short-lived service token the Aegis feed requires.

The claims match ``aegis/security/service_token.py::mint_service_token`` in
aegis-news: EdDSA, header ``kid`` and ``typ: at+jwt``, ``idtyp: app``,
``client_id`` equal to ``sub``, and the single scope ``feed:read``, which
reaches the feed and the mapping list and no route that returns article text.

A token lives ten minutes, well inside Aegis's lifetime cap (one day by
default), and is minted fresh for every run, so nothing long-lived is stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

FEED_SCOPE = "feed:read"
TOKEN_LIFETIME = timedelta(minutes=10)


def load_signing_key(pem: str) -> Ed25519PrivateKey:
    """Read an Ed25519 PEM private key. Accepts "\\n" escapes from one-line env values."""
    text = pem.strip().replace("\\n", "\n")
    key = load_pem_private_key(text.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("AEGIS_SIGNING_KEY must be an Ed25519 private key")
    return key


def mint_feed_token(
    key: Ed25519PrivateKey,
    *,
    key_id: str,
    issuer: str,
    audience: str,
    client_id: str,
    now: datetime | None = None,
    lifetime: timedelta = TOKEN_LIFETIME,
) -> str:
    issued = now or datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": client_id,
            "iat": issued,
            "exp": issued + lifetime,
            "idtyp": "app",
            "client_id": client_id,
            "scope": FEED_SCOPE,
        },
        key,
        algorithm="EdDSA",
        headers={"kid": key_id, "typ": "at+jwt"},
    )
