"""Server-to-server auth for /v1 paper-trading endpoints.

The Next.js side reads the NextAuth session, then calls the FastAPI with
``X-Internal-Token`` (matching settings.internal_api_token) and ``X-User-Id``
(the DB row id). The token confirms the request came from our trusted
Next.js server; the user id identifies whose portfolio to read/mutate.

This is a Phase 6 bridge — Phase 7 will swap in real JWT verification.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from stockviz.settings import get_settings


def require_user_id(
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> int:
    """FastAPI dependency: returns the authenticated user.id or raises 401."""

    settings = get_settings()
    if not settings.internal_api_token:
        # Belt-and-suspenders: never allow access when the token is unset.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal token not configured")

    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")

    if not x_user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-User-Id header required")

    try:
        return int(x_user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-User-Id must be an integer") from exc


UserIdDep = Annotated[int, Depends(require_user_id)]
