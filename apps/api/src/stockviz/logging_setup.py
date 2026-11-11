"""Process logging for the CLI, workers and the scheduler.

Provider keys travel in query strings (Alpha Vantage and NewsData.io take
``apikey=``), and httpx logs every request URL at INFO. With the root logger
at INFO the nightly cron printed the Alpha Vantage key into the Railway logs
on every fallback request (found in the 11 Nov 2026 run). Two layers stop it:

- httpx and httpcore log at WARNING, so request lines are not written at all;
- every handler carries ``RedactSecrets``, which masks credential-looking
  query parameters in any record that still reaches it (an exception text,
  another library, a future logger).

``redact`` is also applied to error text the CLI stores in ``job_runs``,
because ``httpx.HTTPStatusError`` puts the full URL in its message.
"""

from __future__ import annotations

import logging
import re

FORMAT = "%(levelname)s %(name)s: %(message)s"

QUIET_LOGGERS = ("httpx", "httpcore")
"""Libraries whose INFO lines carry request URLs."""

_SECRET_PARAM = re.compile(
    r"(?P<name>\b(?:api[_-]?key|apikey|access[_-]?token|token|key|secret)=)[^&\s\"'#]+",
    re.IGNORECASE,
)

MASK = "***"


def redact(text: str) -> str:
    """Mask the value of every credential-looking ``name=value`` pair."""

    return _SECRET_PARAM.sub(lambda m: m.group("name") + MASK, text)


class RedactSecrets(logging.Filter):
    """Rewrite a record's message, arguments and exception text with ``redact``."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """``basicConfig`` plus the two protections above. Safe to call twice."""

    logging.basicConfig(level=level, format=FORMAT)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactSecrets) for f in handler.filters):
            handler.addFilter(RedactSecrets())
