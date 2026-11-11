"""The one client StockViz uses to read Aegis News.

Only the nightly sync calls it; pages read the copied tables. It reads two
routes, both under the ``feed:read`` scope:

- ``GET /api/v1/feed/documents``: signed document bundles in feed order.
- ``GET /api/v1/assets/mappings``: the instrument mapping list.

Every request carries a freshly minted service token, times out, and is
retried a bounded number of times on a connection error, 429 or 5xx (the
Aegis API sleeps when idle, so the first call can fail while it wakes).
Responses are validated against ``contract.py``; anything else raises
:class:`AegisError`.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from pydantic import ValidationError

from stockviz.services.aegis.contract import AssetMapping, FeedPage, MappingsPage

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRIES = 3
BACKOFF_SECONDS = (2.0, 5.0, 15.0)
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_MAPPING_PAGES = 100


class AegisError(RuntimeError):
    """Aegis answered with an error, an unexpected shape, or not at all."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class AegisClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: Callable[[], str],
        http: httpx.Client | None = None,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http = http or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AegisClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- routes ---------------------------------------------------------------

    def feed_page(self, *, cursor: str | None, limit: int) -> FeedPage:
        """One page of the document feed, from ``cursor`` or from the start."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = self._get("/api/v1/feed/documents", params)
        try:
            return FeedPage.model_validate(body)
        except ValidationError as exc:
            raise AegisError(f"feed response did not match the contract: {exc}") from exc

    def mappings(self, *, limit: int = 100) -> Iterator[AssetMapping]:
        """Every asset mapping, across pages."""
        cursor: str | None = None
        for _ in range(MAX_MAPPING_PAGES):
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            body = self._get("/api/v1/assets/mappings", params)
            try:
                page = MappingsPage.model_validate(body)
            except ValidationError as exc:
                raise AegisError(f"mappings response did not match the contract: {exc}") from exc
            yield from page.data
            if not page.pagination.has_more or not page.pagination.next_cursor:
                return
            cursor = page.pagination.next_cursor
        raise AegisError(f"mapping list longer than {MAX_MAPPING_PAGES} pages")

    # -- transport ------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self._base_url}{path}"
        for attempt in range(MAX_RETRIES + 1):
            last = attempt == MAX_RETRIES
            try:
                response = self._http.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._token()}",
                        "Accept": "application/json",
                    },
                )
            except httpx.TransportError as exc:
                if last:
                    raise AegisError(f"Aegis unreachable: {exc.__class__.__name__}") from exc
                self._wait(attempt, None, f"{exc.__class__.__name__}")
                continue

            if response.status_code in RETRY_STATUSES and not last:
                self._wait(attempt, response.headers.get("Retry-After"), str(response.status_code))
                continue
            if response.status_code >= 400:
                raise _error_from(response)
            try:
                return response.json()
            except ValueError as exc:
                raise AegisError("Aegis returned a body that is not JSON") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait(self, attempt: int, retry_after: str | None, reason: str) -> None:
        delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
        logger.warning("aegis: %s, retrying in %.0fs (attempt %d)", reason, delay, attempt + 1)
        self._sleep(delay)


def _error_from(response: httpx.Response) -> AegisError:
    code: str | None = None
    message = f"Aegis returned HTTP {response.status_code}"
    try:
        error = response.json().get("error") or {}
        code = error.get("code")
        if error.get("message"):
            message = f"{message} {code}: {error['message']}"
    except (ValueError, AttributeError):
        pass
    return AegisError(message, status=response.status_code, code=code)
