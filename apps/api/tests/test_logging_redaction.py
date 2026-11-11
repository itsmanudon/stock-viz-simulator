"""Provider keys never reach the logs or ``job_runs`` (11 Nov 2026 cron run).

The Alpha Vantage fallback sends its key as ``apikey=`` in the query string,
and httpx logged each request URL at INFO, so the hosted cron printed the key
into Railway's log on every fallback call.
"""

from __future__ import annotations

import io
import logging

import httpx
import pytest

from stockviz.logging_setup import MASK, RedactSecrets, configure_logging, redact

KEY = "SECRETKEY123"
URL = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=X&apikey={KEY}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (URL, URL.replace(KEY, MASK)),
        ("GET /latest?apikey=abc&q=AAPL", f"GET /latest?apikey={MASK}&q=AAPL"),
        ("api_key=abc def", f"api_key={MASK} def"),
        ("url 'https://x/y?token=t0k#frag'", f"url 'https://x/y?token={MASK}#frag'"),
        ("no credentials here, 23 documents", "no credentials here, 23 documents"),
    ],
)
def test_redact_masks_credential_parameters(text: str, expected: str) -> None:
    assert redact(text) == expected


def _capture() -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactSecrets())
    logger = logging.getLogger("stockviz.test.redaction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream, handler


def test_filter_masks_formatted_arguments() -> None:
    logger, stream, handler = _capture()
    try:
        logger.info('HTTP Request: GET %s "%s"', URL, "HTTP/1.1 200 OK")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert KEY not in out
    assert f"apikey={MASK}" in out
    assert "HTTP/1.1 200 OK" in out


def test_filter_masks_exception_text() -> None:
    logger, stream, handler = _capture()
    request = httpx.Request("GET", URL)
    response = httpx.Response(429, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logger.exception("fallback failed")
    finally:
        logger.removeHandler(handler)
    assert KEY not in stream.getvalue()


def test_configure_logging_quiets_httpx_and_filters_root_handlers() -> None:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_levels = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    try:
        configure_logging()
        configure_logging()  # idempotent
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
        for handler in root.handlers:
            assert sum(isinstance(f, RedactSecrets) for f in handler.filters) == 1
    finally:
        for handler in root.handlers:
            for f in [f for f in handler.filters if isinstance(f, RedactSecrets)]:
                handler.removeFilter(f)
        root.handlers[:] = saved_handlers
        for name, level in saved_levels.items():
            logging.getLogger(name).setLevel(level)


def test_job_run_error_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI stores an exception's text in ``job_runs.error``."""

    from stockviz import cli

    stored: dict[str, str | None] = {}

    class _Row:
        finished_at = exit_code = status = error = None

    row = _Row()

    class _Session:
        def __init__(self, *_a, **_k) -> None: ...
        def __enter__(self):
            return self

        def __exit__(self, *_a) -> None: ...
        def get(self, *_a):
            return row

        def add(self, _row) -> None: ...
        def commit(self) -> None:
            stored["error"] = row.error

    monkeypatch.setattr(cli, "Session", _Session)
    cli._record_job_end(1, 1, f"HTTPStatusError: Client error '429' for url '{URL}'")
    assert stored["error"] is not None
    assert KEY not in stored["error"]
