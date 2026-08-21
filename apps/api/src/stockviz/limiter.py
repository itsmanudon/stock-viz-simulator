"""slowapi rate limiter.

Two things here are less obvious than they look.

**Disabling.** ``Limiter`` picks ``RATELIMIT_ENABLED`` up from the environment
on its own and keeps it as the *raw string*, so the documented
``RATELIMIT_ENABLED=0`` left ``limiter.enabled == "0"`` — a truthy value — and
the limiter stayed on. We parse the flag ourselves and assign a real bool
after construction so the documented switch actually works.

**Keying.** ``get_remote_address`` reads ``request.client.host``, which behind
Render's load balancer is the proxy for every request — one global bucket for
all users. ``client_key`` prefers the authenticated user id (from the bridge
JWT), then the left-most ``X-Forwarded-For`` hop, then the socket address.
Uvicorn must run with ``--proxy-headers`` for the forwarded chain to be
trusted; the Dockerfile sets that.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _enabled_from_env() -> bool:
    raw = os.getenv("RATELIMIT_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _user_id_from_authorization(request: Request) -> str | None:
    """Best-effort user id from the bridge JWT, without failing the request.

    Rate limiting runs before the endpoint's auth dependency, so this decodes
    opportunistically: an absent or unverifiable token just means we fall back
    to an address-based key. Verification still happens in ``auth.py`` — this
    is only a bucketing hint.
    """
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        return None

    from jose import JWTError
    from jose import jwt as jose_jwt

    from stockviz.settings import get_settings

    try:
        payload = jose_jwt.decode(
            header.removeprefix("Bearer "),
            get_settings().internal_api_token,
            algorithms=["HS256"],
        )
    except (JWTError, ValueError):
        return None
    sub = payload.get("sub")
    return f"user:{sub}" if sub else None


def client_key(request: Request) -> str:
    """Per-user where possible, per-client-IP otherwise."""
    user = _user_id_from_authorization(request)
    if user is not None:
        return user

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Left-most entry is the original client; the rest are proxy hops.
        first = forwarded.split(",")[0].strip()
        if first:
            return f"ip:{first}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=client_key)
# Assign after construction: Limiter's own env handling stores the raw string.
limiter.enabled = _enabled_from_env()
