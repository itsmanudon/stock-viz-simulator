"""Optional bounded cache for pure public computations, disabled by default.

All backend failures compute normally. Loader failures always propagate. Values
are versioned JSON bound to their complete key and response schema; no stale
fallback, private data, distributed locking, or startup network calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from threading import BoundedSemaphore, Lock
from typing import Any, TypeVar

from pydantic import BaseModel

from stockviz.settings import get_settings

T = TypeVar("T", bound=BaseModel)
MAX_PAYLOAD_BYTES = 256 * 1024
ENVELOPE_VERSION = 1
COMMAND_TIMEOUT_SECONDS = 0.04
_UNAVAILABLE = object()
_logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def _schema_id(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(schema.encode()).hexdigest()


class Cache:
    """No-op backend and shared statistics surface."""

    enabled = False

    def __init__(self, namespace: str = "stockviz:local:v1") -> None:
        self.namespace = namespace
        self._lock = Lock()
        self._stats: dict[str, int | float] = dict.fromkeys(
            (
                "hits",
                "misses",
                "sets",
                "errors",
                "invalid",
                "bypass",
                "commands",
                "get_commands",
                "set_commands",
                "command_latency_ms",
                "backend_cpu_ms",
            ),
            0,
        )

    def _count(self, **increments: int | float) -> None:
        with self._lock:
            for name, value in increments.items():
                self._stats[name] += value

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            snapshot = dict(self._stats)
        lookups = snapshot["hits"] + snapshot["misses"]
        snapshot["cache_hit_ratio"] = snapshot["hits"] / lookups if lookups else 0.0
        return snapshot

    def get_or_set(
        self, key: str, loader: Callable[[], T], model: type[T], ttl_seconds: int = 300
    ) -> T:
        self._count(bypass=1)
        return loader()


class RedisCache(Cache):
    enabled = True

    def __init__(
        self,
        client: Any,
        namespace: str,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(namespace)
        self.client = client
        self._clock = clock
        self._monotonic = monotonic
        self._circuit_until = 0.0
        # Bound both active work and queued work, including DNS resolution that
        # Redis socket/connect timeouts do not cover. Threads start on first use.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="stockviz-cache")
        self._capacity = BoundedSemaphore(8)

    def _run_command(self, operation: Callable[[], Any]) -> Any:
        started = time.thread_time_ns()
        try:
            return operation()
        finally:
            self._count(backend_cpu_ms=(time.thread_time_ns() - started) / 1_000_000)

    def _command(self, name: str, operation: Callable[[], Any]) -> Any:
        with self._lock:
            if self._monotonic() < self._circuit_until:
                return _UNAVAILABLE
        if not self._capacity.acquire(blocking=False):
            return _UNAVAILABLE
        started = self._monotonic()
        wall_started = time.monotonic()
        future: Future[Any] | None = None
        try:
            future = self._executor.submit(self._run_command, operation)
            future.add_done_callback(lambda _completed: self._capacity.release())
            remaining = max(0.0, COMMAND_TIMEOUT_SECONDS - (time.monotonic() - wall_started))
            return future.result(timeout=remaining)
        except Exception as exc:
            if future is None:
                self._capacity.release()
            # Only backend I/O is inside this handler. Never swallow computation errors.
            with self._lock:
                self._circuit_until = self._monotonic() + 30
                self._stats["errors"] += 1
            _logger.warning(
                "cache.backend_unavailable",
                extra={
                    "event": "cache.backend_unavailable",
                    "cache_family": "indicators",
                    "operation": name,
                    "error_type": type(exc).__name__,
                },
            )
            return _UNAVAILABLE
        finally:
            # Caller-observed command wait; abandoned DNS work may finish later.
            self._count(
                commands=1,
                **{f"{name}_commands": 1},
                command_latency_ms=max(0.0, self._monotonic() - started) * 1000,
            )

    def _decode(self, raw: bytes | str, key: str, model: type[T]) -> T:
        if len(raw.encode() if isinstance(raw, str) else raw) > MAX_PAYLOAD_BYTES:
            raise ValueError("oversized envelope")
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("invalid envelope")
        expires = envelope.get("expires_at")
        if (
            type(envelope.get("version")) is not int
            or envelope.get("version") != ENVELOPE_VERSION
            or envelope.get("key") != key
            or envelope.get("schema") != _schema_id(model)
            or not isinstance(expires, (int, float))
            or isinstance(expires, bool)
            or not math.isfinite(expires)
            or expires <= self._clock()
            or not isinstance(envelope.get("payload"), str)
        ):
            raise ValueError("incompatible or expired envelope")
        return model.model_validate_json(envelope["payload"])

    def get_or_set(
        self, key: str, loader: Callable[[], T], model: type[T], ttl_seconds: int = 300
    ) -> T:
        if ttl_seconds <= 0:
            self._count(bypass=1)
            return loader()
        expires = self._clock() + ttl_seconds
        full_key = key if key.startswith(f"{self.namespace}:") else f"{self.namespace}:{key}"
        raw = self._command("get", lambda: self.client.get(full_key))
        if raw is _UNAVAILABLE:
            self._count(bypass=1)
            return loader()
        if raw is not None:
            try:
                value = self._decode(raw, full_key, model)
            except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
                self._count(invalid=1)
            else:
                self._count(hits=1)
                return value

        self._count(misses=1)
        value = loader()
        try:
            encoded = json.dumps(
                {
                    "version": ENVELOPE_VERSION,
                    "key": full_key,
                    "schema": _schema_id(model),
                    "expires_at": expires,
                    "payload": value.model_dump_json(),
                },
                separators=(",", ":"),
            ).encode()
        except (ValueError, TypeError):
            self._count(bypass=1)
            return value
        remaining_ms = int((expires - self._clock()) * 1000)
        if remaining_ms <= 0 or len(encoded) > MAX_PAYLOAD_BYTES:
            self._count(bypass=1)
            return value
        result = self._command("set", lambda: self.client.set(full_key, encoded, px=remaining_ms))
        if result is _UNAVAILABLE:
            self._count(bypass=1)
        else:
            self._count(sets=1)
        return value


@lru_cache(maxsize=1)
def get_cache() -> Cache:
    settings = get_settings()
    if settings.cache_backend == "none":
        return Cache(settings.cache_namespace)

    # Lazy import keeps disabled baseline runs independent of redis-py.
    from redis import ConnectionPool, Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    pool = ConnectionPool.from_url(
        settings.redis_url,
        password=settings.redis_password.get_secret_value(),
        max_connections=8,
        socket_timeout=0.02,
        socket_connect_timeout=0.02,
        retry=Retry(NoBackoff(), 0),
        retry_on_error=[],
        retry_on_timeout=False,
        health_check_interval=0,
        decode_responses=False,
    )
    return RedisCache(Redis(connection_pool=pool), settings.cache_namespace)
