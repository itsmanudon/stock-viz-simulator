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
JWT), then the ``X-Forwarded-For`` hop our own proxy added, then the socket
address. The left-most entry is whatever the client sent, so it is never
used: the address is taken ``TRUSTED_PROXY_HOPS`` entries from the right
(default 1, Railway's edge; 0 ignores the header). The web server reads the
header the same way (``apps/web/lib/client-address.ts``).

**The web server is exempt (audit RS-6, option 1).** On Railway the web
server reaches the API over the private network with no forwarded address,
so every visitor of every server-rendered page landed in one bucket keyed on
the web container. The web server now sends ``X-StockViz-Web``, an HMAC of a
fixed label under ``INTERNAL_API_TOKEN`` (which both services hold), on its
server-side calls, and the limiter skips those requests. The web server
limits each visitor itself, by their real address, on the query-driven
pages (``apps/web/lib/visitor-limit.ts``). The header never varies, so it
does not split Next's fetch cache. Browser calls (option quotes, backtests)
reach the API through Railway's edge without it and stay limited here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from functools import lru_cache

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

    forwarded = forwarded_client(request.headers.get("x-forwarded-for"))
    if forwarded:
        return f"ip:{forwarded}"
    return f"ip:{get_remote_address(request)}"


def trusted_proxy_hops(raw: str | None = None) -> int:
    """``TRUSTED_PROXY_HOPS``: how many proxies of ours append to the chain."""
    value = os.getenv("TRUSTED_PROXY_HOPS") if raw is None else raw
    try:
        hops = int((value or "").strip())
    except ValueError:
        return 1
    return hops if hops >= 0 else 1


def forwarded_client(header: str | None, hops: int | None = None) -> str | None:
    """The chain entry our nearest trusted proxy added, or None.

    Each proxy appends the address it received the request from, so the
    client-chosen values sit on the left. Counting ``hops`` from the right
    lands on the address our outermost proxy saw.
    """
    hops = trusted_proxy_hops() if hops is None else hops
    if hops <= 0 or not header:
        return None
    chain = [part.strip() for part in header.split(",") if part.strip()]
    if not chain:
        return None
    return chain[max(len(chain) - hops, 0)]


WEB_SERVER_HEADER = "x-stockviz-web"
_WEB_SERVER_LABEL = b"stockviz-web-server-rate-limit-v1"


@lru_cache(maxsize=4)
def web_server_key(secret: str) -> str:
    """The value the web server sends in ``X-StockViz-Web``."""
    return hmac.new(secret.encode(), _WEB_SERVER_LABEL, hashlib.sha256).hexdigest()


def is_web_server(request: Request) -> bool:
    """Whether ``request`` carries the web server's key."""
    supplied = request.headers.get(WEB_SERVER_HEADER)
    if not supplied:
        return False

    from stockviz.settings import get_settings

    expected = web_server_key(get_settings().internal_api_token)
    return hmac.compare_digest(supplied.encode(), expected.encode())


class _WebServerExemptLimiter(Limiter):
    """slowapi's request filters take no arguments, so the exemption is made
    where the request is known. ``tests/test_rate_limit_web_server.py`` pins
    the behaviour against the installed slowapi."""

    def _check_request_limit(self, request, endpoint_func, in_middleware=True):  # type: ignore[no-untyped-def]
        if is_web_server(request):
            # The decorator reads this after the endpoint runs, to add the
            # rate-limit headers; None means no limit applied.
            request.state.view_rate_limit = None
            return
        super()._check_request_limit(request, endpoint_func, in_middleware)


limiter = _WebServerExemptLimiter(key_func=client_key)
# Assign after construction: Limiter's own env handling stores the raw string.
limiter.enabled = _enabled_from_env()
