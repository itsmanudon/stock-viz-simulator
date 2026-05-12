"""JWT-based auth for /v1 paper-trading endpoints.

The Next.js server mints a short-lived HS256 JWT (``{ sub: "<db_user_id>" }``,
60 s expiry) signed with ``INTERNAL_API_TOKEN`` and sends it as
``Authorization: Bearer <token>``. This dependency verifies the signature and
returns the numeric user id.

Compared to the old ``X-Internal-Token`` + ``X-User-Id`` header bridge:
- The user id is a cryptographically signed claim — it cannot be forged
  without knowing the secret.
- Tokens expire after 60 seconds, limiting replay-attack windows.
- Standard ``Authorization: Bearer`` interface instead of custom headers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError
from jose import jwt as jose_jwt

from stockviz.settings import get_settings


def require_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> int:
    """FastAPI dependency: verifies the Bearer JWT and returns the user.id."""

    settings = get_settings()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authorization header required")

    token = authorization.removeprefix("Bearer ")

    try:
        payload = jose_jwt.decode(token, settings.internal_api_token, algorithms=["HS256"])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc


UserIdDep = Annotated[int, Depends(require_user_id)]
