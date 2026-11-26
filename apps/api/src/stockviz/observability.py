"""Sentry bootstrap.

No-op when ``SENTRY_DSN`` is empty so local dev / CI / tests don't ship
errors anywhere. The deployed server sets the DSN via env.
"""

from __future__ import annotations

import logging
from typing import Any

from stockviz.settings import Settings

logger = logging.getLogger(__name__)


PRIVATE_PATHS = ("/imports", "/opening-lots", "/import-maps")
"""A5.3: routes whose bodies are personal financial records."""


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry ``before_send``: an import route's event loses its request body,
    query string and any local variables, so no tradebook cell reaches Sentry."""
    del hint
    request = event.get("request") or {}
    url = str(request.get("url") or "")
    if any(part in url for part in PRIVATE_PATHS):
        request.pop("data", None)
        request.pop("query_string", None)
        for exc in (event.get("exception") or {}).get("values") or []:
            for frame in (exc.get("stacktrace") or {}).get("frames") or []:
                frame.pop("vars", None)
    return event


def init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry-sdk not installed; skipping init")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=scrub_event,  # type: ignore[arg-type]
    )
    logger.info("sentry initialized (env=%s)", settings.environment)
