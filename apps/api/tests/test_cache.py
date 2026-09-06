"""Optional pure-computation cache contracts; no network or Redis server required."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from stockviz.settings import Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "cache_backend": "none",
            "redis_url": "",
            "redis_password": "",
            "cache_namespace": "stockviz:local:v1",
            "environment": "development",
            **overrides,
        }
    )


class Result(BaseModel):
    amount: Decimal


class FakeClock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeRedis:
    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.calls: list[tuple] = []
        self.failure: Exception | None = None

    def get(self, key):
        self.calls.append(("get", key))
        if self.failure:
            raise self.failure
        return self.values.get(key)

    def set(self, key, value, *, px):
        self.calls.append(("set", key, px))
        if self.failure:
            raise self.failure
        self.values[key] = value.encode() if isinstance(value, str) else value


def test_disabled_cache_always_computes_without_redis_import(monkeypatch) -> None:
    import sys

    from stockviz.services.cache import get_cache

    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setattr("stockviz.services.cache.get_settings", lambda: _settings())
    get_cache.cache_clear()
    try:
        cache = get_cache()
        assert cache.enabled is False
        assert cache.namespace == "stockviz:local:v1"
        assert cache.get_or_set("key", lambda: Result(amount=Decimal(1)), Result).amount == 1
        assert cache.get_or_set("key", lambda: Result(amount=Decimal(2)), Result).amount == 2
        assert cache.stats()["commands"] == 0
        assert cache.stats()["bypass"] == 2
    finally:
        get_cache.cache_clear()


def test_miss_then_hit_preserves_exact_decimal_and_namespace() -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "stockviz:test:v1", clock=clock, monotonic=clock)
    exact = Decimal("123456789123456789.123456789")
    assert cache.get_or_set("input-digest", lambda: Result(amount=exact), Result).amount == exact

    def unexpected_loader():
        pytest.fail("a valid cache hit must avoid recomputation")

    assert cache.get_or_set("input-digest", unexpected_loader, Result).amount == exact
    assert list(client.values) == ["stockviz:test:v1:input-digest"]
    assert client.calls == [
        ("get", "stockviz:test:v1:input-digest"),
        ("set", "stockviz:test:v1:input-digest", 300000),
        ("get", "stockviz:test:v1:input-digest"),
    ]
    stats = cache.stats()
    assert (stats["hits"], stats["misses"], stats["sets"], stats["commands"]) == (1, 1, 1, 3)


@pytest.mark.parametrize("backend", ["unknown", "REDIS"])
def test_unknown_cache_backend_fails_fast(backend) -> None:
    with pytest.raises(ValidationError):
        _settings(cache_backend=backend)


@pytest.mark.parametrize("url,password", [("", "secret"), ("redis://localhost:6379/0", "")])
def test_redis_requires_explicit_url_and_password(url, password) -> None:
    with pytest.raises(ValidationError, match="REDIS"):
        _settings(cache_backend="redis", redis_url=url, redis_password=password)


@pytest.mark.parametrize("environment", ["production", "prod", " PROD "])
def test_redis_pilot_cannot_run_in_production(environment) -> None:
    with pytest.raises(ValidationError, match="Redis pilot"):
        _settings(
            environment=environment,
            internal_api_token="private-token",
            cache_backend="redis",
            redis_url="redis://localhost:6379/0",
            redis_password="secret",
        )


@pytest.mark.parametrize("namespace", ["", "stockviz:*", "stockviz\nkey", "x" * 129])
def test_cache_namespace_rejects_unsafe_keys(namespace) -> None:
    with pytest.raises(ValidationError, match="namespace"):
        _settings(cache_namespace=namespace)


def test_redis_password_is_redacted() -> None:
    settings = _settings(
        cache_backend="redis",
        redis_url="redis://localhost:6379/0",
        redis_password="private-test-password",
    )
    assert settings.redis_password.get_secret_value() == "private-test-password"
    assert "private-test-password" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/0",
        "redis://u:pw@localhost/0",
        "redis://@localhost/0",
        "redis://localhost/0?socket_timeout=30",
    ],
)
def test_redis_url_cannot_override_password_or_transport_policy(url) -> None:
    with pytest.raises(ValidationError, match="REDIS_URL"):
        _settings(cache_backend="redis", redis_url=url, redis_password="secret")


def test_ttl_is_anchored_before_loader_and_hits_do_not_extend_it() -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "test", clock=clock, monotonic=clock)

    def slow_loader():
        clock.now += 2
        return Result(amount=Decimal(7))

    cache.get_or_set("key", slow_loader, Result, ttl_seconds=5)
    assert client.calls[-1] == ("set", "test:key", 3000)
    clock.now = 1004
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 7
    assert sum(call[0] == "set" for call in client.calls) == 1
    clock.now = 1005
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 9
    assert cache.stats()["invalid"] == 1


def test_slow_loader_cannot_publish_expired_result() -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "test", clock=clock, monotonic=clock)

    def slow_loader():
        clock.now += 5
        return Result(amount=Decimal(7))

    assert cache.get_or_set("key", slow_loader, Result, ttl_seconds=5).amount == 7
    assert client.values == {}


@pytest.mark.parametrize(
    "mutation",
    [
        "json",
        "version",
        "key",
        "schema",
        "payload",
        "expires_at",
        "large",
        "bool-version",
        "nan-expiry",
    ],
)
def test_invalid_envelopes_recompute_without_serving_stale_or_misbound_values(mutation) -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "test", clock=clock, monotonic=clock)
    cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result)
    envelope = json.loads(client.values["test:key"])
    if mutation == "json":
        client.values["test:key"] = b"not-json"
    elif mutation == "large":
        client.values["test:key"] = b" " * (256 * 1024 + 1)
    elif mutation == "bool-version":
        envelope["version"] = True
        client.values["test:key"] = json.dumps(envelope).encode()
    elif mutation == "nan-expiry":
        envelope["expires_at"] = float("nan")
        client.values["test:key"] = json.dumps(envelope).encode()
    else:
        envelope[mutation] = {
            "version": 99,
            "key": "other",
            "schema": "unknown",
            "payload": '{"amount": "not-a-decimal"}',
            "expires_at": "never",
        }[mutation]
        client.values["test:key"] = json.dumps(envelope).encode()
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 9
    assert cache.stats()["invalid"] == 1


def test_schema_changes_do_not_reuse_a_previous_model() -> None:
    from stockviz.services.cache import RedisCache

    class Changed(BaseModel):
        amount: Decimal
        currency: str

    client = FakeRedis()
    cache = RedisCache(client, "test")
    cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result)
    result = cache.get_or_set("key", lambda: Changed(amount=Decimal(9), currency="EUR"), Changed)
    assert result.currency == "EUR"
    assert result.amount == 9
    assert cache.stats()["invalid"] == 1


@pytest.mark.parametrize(
    "failure", [ConnectionError("down"), TimeoutError("slow"), RuntimeError("pool exhausted")]
)
def test_redis_errors_open_circuit_and_recover_after_30_seconds(failure) -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "test", clock=clock, monotonic=clock)
    client.failure = failure
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(1)), Result).amount == 1
    client.failure = None
    clock.now += 29
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(2)), Result).amount == 2
    assert len(client.calls) == 1
    clock.now += 1
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(3)), Result).amount == 3
    assert len(client.calls) == 3
    assert cache.stats()["errors"] == 1


def test_loader_errors_propagate_without_cached_stale_fallback() -> None:
    from stockviz.services.cache import RedisCache

    client, clock = FakeRedis(), FakeClock()
    cache = RedisCache(client, "test", clock=clock, monotonic=clock)
    cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result, ttl_seconds=1)
    clock.now += 1

    def failing_loader():
        raise ValueError("calculation failed")

    with pytest.raises(ValueError, match="calculation failed"):
        cache.get_or_set("key", failing_loader, Result)
    assert cache.stats()["errors"] == 0
    assert cache.stats()["sets"] == 1


def test_oversize_payload_is_returned_without_cache_write() -> None:
    from stockviz.services.cache import RedisCache

    class Large(BaseModel):
        text: str

    client = FakeRedis()
    cache = RedisCache(client, "test")
    value = Large(text="x" * 256 * 1024)
    assert cache.get_or_set("key", lambda: value, Large) == value
    assert client.values == {}
    assert cache.stats()["bypass"] == 1


def test_concurrent_misses_are_safe_and_stats_count_all_calls() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "test")
    barrier = Barrier(8)

    def loader():
        barrier.wait(timeout=3)
        return Result(amount=Decimal("1.23456789"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: cache.get_or_set("key", loader, Result), range(8)))
    assert all(value.amount == Decimal("1.23456789") for value in results)
    assert cache.stats()["misses"] == 8
    assert cache.stats()["sets"] == 8
    assert cache.stats()["commands"] == 16
    snapshot = cache.stats()
    snapshot["sets"] = 0
    assert cache.stats()["sets"] == 8


def test_redis_factory_is_lazy_and_has_bounded_pool_and_timeout(monkeypatch) -> None:
    from stockviz.services.cache import RedisCache, get_cache

    settings = _settings(
        cache_backend="redis",
        redis_url="redis://localhost:16381/0",
        redis_password="secret",
    )
    monkeypatch.setattr("stockviz.services.cache.get_settings", lambda: settings)
    get_cache.cache_clear()
    try:
        cache = get_cache()
        assert isinstance(cache, RedisCache)
        assert cache.enabled
        pool = cache.client.connection_pool
        assert pool.max_connections == 8
        assert pool.connection_kwargs["socket_timeout"] == 0.02
        assert pool.connection_kwargs["socket_connect_timeout"] == 0.02
        assert pool._created_connections == 0
    finally:
        get_cache.cache_clear()


def test_set_failure_returns_computed_value_and_opens_circuit() -> None:
    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "test")

    def loader():
        client.failure = TimeoutError("set unavailable")
        return Result(amount=Decimal(7))

    assert cache.get_or_set("key", loader, Result).amount == 7
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 9
    assert [call[0] for call in client.calls] == ["get", "set"]
    assert cache.stats()["errors"] == 1
    assert cache.stats()["sets"] == 0


@pytest.mark.parametrize("ttl", [0, -1])
def test_nonpositive_ttl_bypasses_network(ttl) -> None:
    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "test")
    assert (
        cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result, ttl_seconds=ttl).amount
        == 7
    )
    assert client.calls == []


def test_command_latency_accumulates_without_counting_loader_time() -> None:
    from stockviz.services.cache import RedisCache

    clock = FakeClock()

    class SlowRedis(FakeRedis):
        def get(self, key):
            clock.now += 0.002
            return super().get(key)

        def set(self, key, value, *, px):
            clock.now += 0.003
            return super().set(key, value, px=px)

    cache = RedisCache(SlowRedis(), "test", clock=clock, monotonic=clock)

    def loader():
        clock.now += 0.1
        return Result(amount=Decimal(7))

    cache.get_or_set("key", loader, Result)
    assert cache.stats()["command_latency_ms"] == pytest.approx(5)


def test_full_keys_keep_one_namespace_prefix_and_report_hit_ratio() -> None:
    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "stockviz:test:v1")
    cache.get_or_set(
        "stockviz:test:v1:indicators:v1:abc", lambda: Result(amount=Decimal(7)), Result
    )
    assert list(client.values) == ["stockviz:test:v1:indicators:v1:abc"]
    cache.get_or_set(
        "stockviz:test:v1:indicators:v1:abc", lambda: Result(amount=Decimal(9)), Result
    )
    assert cache.stats()["cache_hit_ratio"] == 0.5


def test_namespaces_cannot_read_each_others_values() -> None:
    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    first = RedisCache(client, "first")
    second = RedisCache(client, "second")
    first.get_or_set("key", lambda: Result(amount=Decimal(7)), Result)
    assert second.get_or_set("first:key", lambda: Result(amount=Decimal(9)), Result).amount == 9
    assert set(client.values) == {"first:key", "second:first:key"}


@pytest.mark.parametrize("raw", [b"[" * 2000 + b"]" * 2000, None])
def test_pathological_json_is_a_miss_not_an_api_error(raw) -> None:
    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "test")
    cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result)
    if raw is None:
        envelope = json.loads(client.values["test:key"])
        envelope["expires_at"] = 10**1000
        raw = json.dumps(envelope).encode()
    client.values["test:key"] = raw
    assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 9
    assert cache.stats()["invalid"] == 1


@pytest.mark.parametrize(
    "suffix",
    [
        ":notaport",
        ":0",
        ":65536",
        ":99999",
        ":-1",
        ":",
        "/notadb",
        "/-1",
        "/16",
        "/100",
        "/0/1",
        "/%30",
        "/0%2f1",
        "/+1",
        "/1.0",
        "/ 1",
    ],
)
def test_invalid_redis_port_or_database_fails_in_settings(suffix) -> None:
    with pytest.raises(ValidationError, match="REDIS_URL"):
        _settings(
            cache_backend="redis", redis_url=f"redis://localhost{suffix}", redis_password="secret"
        )


@pytest.mark.parametrize(
    "url",
    [
        "redis://localhost",
        "redis://localhost/",
        "redis://localhost/0",
        "rediss://localhost:6380/15",
        "redis://[::1]:16381/1",
    ],
)
def test_valid_redis_ports_and_pilot_databases_are_accepted(url) -> None:
    assert _settings(cache_backend="redis", redis_url=url, redis_password="secret").redis_url == url


@pytest.mark.parametrize("operation", ["get", "set"])
def test_backend_warning_is_structured_and_never_contains_sensitive_context(
    caplog, operation
) -> None:
    import logging

    from stockviz.services.cache import RedisCache

    client = FakeRedis()
    cache = RedisCache(client, "private-namespace")
    backend_error = TimeoutError("redis://private-host:6379 secret-password private-key")
    if operation == "get":
        client.failure = backend_error

    def loader():
        if operation == "set":
            client.failure = backend_error
        return Result(amount=Decimal(7))

    with caplog.at_level(logging.WARNING, logger="stockviz.services.cache"):
        assert cache.get_or_set("private-key", loader, Result).amount == 7
        assert cache.get_or_set("private-key", loader, Result).amount == 7
    records = [record for record in caplog.records if record.name == "stockviz.services.cache"]
    assert len(records) == 1
    record = records[0]
    assert record.event == "cache.backend_unavailable"
    assert record.cache_family == "indicators"
    assert record.operation == operation
    assert record.error_type == "TimeoutError"
    assert record.exc_info is None
    assert not any(
        secret in str(vars(record))
        for secret in [
            "private-host",
            "secret-password",
            "private-key",
            "private-namespace",
        ]
    )


def test_command_wall_time_is_bounded_even_when_dns_or_client_blocks() -> None:
    import time
    from threading import Event

    from stockviz.services.cache import RedisCache

    release = Event()
    finished = Event()

    class BlockingRedis(FakeRedis):
        def get(self, key):
            try:
                release.wait(timeout=0.3)
                return super().get(key)
            finally:
                finished.set()

    client = BlockingRedis()
    cache = RedisCache(client, "test")
    try:
        started = time.monotonic()
        assert cache.get_or_set("key", lambda: Result(amount=Decimal(7)), Result).amount == 7
        assert time.monotonic() - started < 0.15
        assert cache.stats()["errors"] == 1
        # While the first command is still blocked, the open circuit bypasses it.
        assert cache.get_or_set("key", lambda: Result(amount=Decimal(9)), Result).amount == 9
        assert cache.stats()["commands"] == 1
    finally:
        release.set()
        assert finished.wait(timeout=1)
        if hasattr(cache, "_executor"):
            cache._executor.shutdown(wait=True)


def test_command_capacity_is_bounded_without_queueing_more_work() -> None:
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from stockviz.services.cache import RedisCache

    release = Event()
    entered = Barrier(9)

    class BlockingRedis(FakeRedis):
        def get(self, key):
            self.calls.append(("get", key))
            entered.wait(timeout=2)
            release.wait(timeout=1)
            return None

    client = BlockingRedis()
    cache = RedisCache(client, "test")
    workers = ThreadPoolExecutor(max_workers=8)
    futures = [
        workers.submit(cache.get_or_set, str(i), lambda: Result(amount=Decimal(7)), Result)
        for i in range(8)
    ]
    try:
        entered.wait(timeout=2)
        started = time.monotonic()
        assert cache.get_or_set("ninth", lambda: Result(amount=Decimal(9)), Result).amount == 9
        assert time.monotonic() - started < 0.1
        assert len(client.calls) == 8
    finally:
        release.set()
        workers.shutdown(wait=True)
        if hasattr(cache, "_executor"):
            cache._executor.shutdown(wait=True)
    assert all(future.result().amount == 7 for future in futures)


@pytest.mark.parametrize("backend_fails", [False, True])
def test_backend_cpu_counts_worker_commands_even_on_error_but_excludes_loader(
    monkeypatch, backend_fails
) -> None:
    from stockviz.services.cache import RedisCache

    cpu_ns = 0
    monkeypatch.setattr("stockviz.services.cache.time.thread_time_ns", lambda: cpu_ns)

    class MeasuredRedis(FakeRedis):
        def get(self, key):
            nonlocal cpu_ns
            cpu_ns += 6_000_000
            if backend_fails:
                raise TimeoutError("backend unavailable")
            return super().get(key)

        def set(self, key, value, *, px):
            nonlocal cpu_ns
            cpu_ns += 4_000_000
            return super().set(key, value, px=px)

    def loader():
        nonlocal cpu_ns
        cpu_ns += 100_000_000
        return Result(amount=Decimal(7))

    cache = RedisCache(MeasuredRedis(), "test")
    try:
        assert cache.stats()["backend_cpu_ms"] == 0
        assert cache.get_or_set("key", loader, Result).amount == 7
        assert cache.stats()["backend_cpu_ms"] == (6 if backend_fails else 10)
    finally:
        cache._executor.shutdown(wait=True)
