"""Request ids for the API (audit OP-9, Phase 7.5).

Every request gets an id: the caller's ``X-Request-ID`` when it is a plain
token of up to 64 characters (the web server sends one per API call), else a
new one. It is put in every log line of the request, tagged on Sentry events,
and returned in the response's ``X-Request-ID``, so a page error can be
traced to the API's log.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from stockviz.logging_setup import REQUEST_ID

HEADER = "X-Request-ID"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id_for(supplied: str | None) -> str:
    if supplied and _VALID.match(supplied):
        return supplied
    return uuid.uuid4().hex


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    rid = request_id_for(request.headers.get(HEADER))
    token = REQUEST_ID.set(rid)
    try:
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", rid)
        except ImportError:  # pragma: no cover - sentry is a dependency
            pass
        response = await call_next(request)
    finally:
        REQUEST_ID.reset(token)
    response.headers[HEADER] = rid
    return response
