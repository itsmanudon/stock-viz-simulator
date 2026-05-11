"""Sentry bootstrap.

No-op when ``SENTRY_DSN`` is empty so local dev / CI / tests don't ship
errors anywhere. The deployed server sets the DSN via env.
"""

from __future__ import annotations

import logging

from stockviz.settings import Settings

logger = logging.getLogger(__name__)


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
    )
    logger.info("sentry initialized (env=%s)", settings.environment)
