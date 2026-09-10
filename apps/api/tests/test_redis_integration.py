"""Opt-in real Redis checks. Every test owns and deletes only its UUID namespace."""

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel
from redis import Redis

from stockviz.services.cache import RedisCache

pytestmark = pytest.mark.skipif(
    not os.getenv("STOCKVIZ_TEST_REDIS_URL"), reason="isolated test Redis not configured"
)


class Amount(BaseModel):
    amount: Decimal


@pytest.fixture
def redis_cache():
    client = Redis.from_url(
        os.environ["STOCKVIZ_TEST_REDIS_URL"],
        password=os.environ["STOCKVIZ_TEST_REDIS_PASSWORD"],
        socket_timeout=0.2,
        socket_connect_timeout=0.2,
    )
    assert client.ping()
    namespace = f"stockviz:test:{uuid4().hex}:v1"
    cache = RedisCache(client, namespace)
    try:
        yield cache
    finally:
        keys = list(client.scan_iter(match=f"{namespace}:*"))
        if keys:
            client.delete(*keys)
        client.close()


def test_real_hit_ttl_corruption_and_memory(redis_cache):
    cache = redis_cache
    original = Amount(amount=Decimal("123456789012.123456"))
    assert cache.get_or_set("amount", lambda: original, Amount) == original
    assert cache.get_or_set("amount", lambda: Amount(amount=Decimal(0)), Amount) == original
    key = f"{cache.namespace}:amount"
    assert 0 < cache.client.pttl(key) <= 300_000
    assert cache.client.memory_usage(key) > 0
    cache.client.set(key, b"invalid JSON")
    assert cache.get_or_set("amount", lambda: original, Amount) == original
    assert cache.stats()["invalid"] == 1
    assert cache.stats()["hits"] == 1


def test_real_deleted_cache_and_independent_client_recompute(redis_cache):
    cache = redis_cache
    cache.get_or_set("amount", lambda: Amount(amount=Decimal(7)), Amount)
    second = RedisCache(cache.client, cache.namespace)
    assert second.get_or_set("amount", lambda: Amount(amount=Decimal(8)), Amount).amount == 7
    cache.client.delete(f"{cache.namespace}:amount")
    assert second.get_or_set("amount", lambda: Amount(amount=Decimal(8)), Amount).amount == 8
    assert second.stats()["misses"] == 1
