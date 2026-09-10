"""Read-only local API benchmark. Run in an isolated process, never a live worker.

DATABASE_URL selects a populated *development* PostgreSQL database. Connections
are forced read-only; a portfolio must already exist. BENCH_SAMPLES defaults to
300; BENCH_OVERVIEW=1 includes the new combined view. JSONL goes to stdout.
"""

import os

os.environ.update(DEBUG="false", ENABLE_SCHEDULER="false", SENTRY_DSN="", RATELIMIT_ENABLED="false")

import functools
import hashlib
import json
import math
import pathlib
import platform
import random
import time
from collections import Counter
from datetime import UTC, datetime

import fastapi.routing
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import event, text

import stockviz
from stockviz.db import engine
from stockviz.main import app
from stockviz.settings import get_settings

try:
    from stockviz.services.cache import get_cache
except ImportError:  # Original pre-P0 image intentionally has no cache module.
    get_cache = None

state = None


@event.listens_for(engine, "connect")
def readonly(connection, record):
    connection.read_only = True


@event.listens_for(engine, "before_cursor_execute")
def before(conn, cursor, statement, parameters, context, executemany):
    context.bench_start = time.perf_counter_ns()
    if state is not None:
        state["queries"] += 1


@event.listens_for(engine, "after_cursor_execute")
def after(conn, cursor, statement, parameters, context, executemany):
    if state is not None:
        state["db_ms"] += (time.perf_counter_ns() - context.bench_start) / 1e6


def wrap_endpoint(original):
    @functools.wraps(original)
    def measured(*args, **kwargs):
        start = time.thread_time_ns()
        try:
            return original(*args, **kwargs)
        finally:
            if state is not None:
                state["endpoint_cpu_ms"] += (time.thread_time_ns() - start) / 1e6

    return measured


async def measured_endpoint(*, dependant, values, is_coroutine):
    if is_coroutine:
        return await dependant.call(**values)
    return await fastapi.routing.run_in_threadpool(wrap_endpoint(dependant.call), **values)


fastapi.routing.run_endpoint_function = measured_endpoint


class TimedApp:
    async def __call__(self, scope, receive, send):
        start = time.perf_counter_ns()

        async def measured_send(message):
            if (
                state is not None
                and message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                state["server_ms"] += (time.perf_counter_ns() - start) / 1e6
            await send(message)

        await app(scope, receive, measured_send)


def emit(value):
    print(json.dumps(value, default=str), flush=True)


source_root = pathlib.Path(stockviz.__file__).parent
emit(
    {
        "kind": "source",
        "python": platform.python_version(),
        "files": {
            str(path.relative_to(source_root)): hashlib.sha256(
                path.read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for path in sorted(source_root.rglob("*.py"))
        },
    }
)


with engine.connect() as conn:
    user_id = conn.execute(
        text(
            "SELECT p.user_id FROM portfolios p JOIN positions x ON x.portfolio_id=p.id GROUP BY p.user_id ORDER BY count(*) DESC,p.user_id LIMIT 1"
        )
    ).scalar_one()
    counts = {
        table: conn.execute(text("SELECT count(*) FROM " + table)).scalar_one()
        for table in (
            "symbols",
            "price_bars",
            "positions",
            "portfolio_snapshots",
            "news_articles",
            "news_sentiment",
            "options_positions",
        )
    }
    emit(
        {
            "kind": "inventory",
            "utc": datetime.now(UTC),
            "counts": counts,
            "read_only": conn.execute(text("SHOW transaction_read_only")).scalar_one(),
        }
    )

paths = {
    "markets": ["/v1/markets/summary?sparkline_days=30"],
    "momentum": ["/v1/symbols/screen?momentum_days=30"],
    "portfolio": ["/v1/portfolio"],
    "analytics": ["/v1/portfolio/analytics"],
    "portfolio_pair": ["/v1/portfolio", "/v1/portfolio/analytics"],
    "AAPL_indicators": ["/v1/symbols/AAPL/indicators?names=sma_20,sma_50,rsi_14,macd&limit=252"],
    "NVDA_indicators": ["/v1/symbols/NVDA/indicators?names=sma_20,sma_50,rsi_14,macd&limit=252"],
    "screener": ["/v1/symbols/screen"],
    "recommendations": ["/v1/recommendations?limit=100"],
    "bars": ["/v1/symbols/AAPL/bars?limit=252"],
}
if os.getenv("BENCH_OVERVIEW") == "1":
    paths["overview"] = ["/v1/portfolio/overview"]
if os.getenv("BENCH_PATHS"):
    paths = {name: paths[name] for name in os.environ["BENCH_PATHS"].split(",")}
count = int(os.getenv("BENCH_SAMPLES", "300"))
samples = {name: [] for name in paths}
hashes = {name: set() for name in paths}
payloads = {}


def run(client, name):
    global state
    if os.getenv("BENCH_COLD") == "1" and get_cache and get_cache().enabled:
        # Controlled cache-cold run only. Delete this isolated benchmark's
        # keys outside the timed request; never FLUSHDB or touch other namespaces.
        cache = get_cache()
        if not cache.namespace.startswith("stockviz:pilot-"):
            raise ValueError("BENCH_COLD requires a dedicated stockviz:pilot-... namespace")
        keys = list(cache.client.scan_iter(match=f"{cache.namespace}:*"))
        if keys:
            cache.client.delete(*keys)
    token = jwt.encode(
        {"sub": str(user_id), "exp": int(time.time()) + 60},
        get_settings().internal_api_token,
        algorithm="HS256",
    )
    cache_before = get_cache().stats() if get_cache else {}
    state = {"queries": 0, "db_ms": 0.0, "endpoint_cpu_ms": 0.0, "server_ms": 0.0, "bytes": 0}
    responses = []
    for path in paths[name]:
        response = client.get(
            path,
            headers={"Authorization": "Bearer " + token}
            if path.startswith("/v1/portfolio")
            else {},
        )
        if response.status_code != 200:
            raise RuntimeError(f"{name}: {response.status_code} {response.text[:200]}")
        responses.append(response.json())
        state["bytes"] += len(response.content)
    result = state
    state = None
    if get_cache:
        cache_after = get_cache().stats()
        for metric in ("hits", "misses", "errors", "bypass"):
            result[f"cache_{metric}"] = cache_after[metric] - cache_before[metric]
        result["cache_worker_cpu_ms"] = cache_after.get("backend_cpu_ms", 0) - cache_before.get(
            "backend_cpu_ms", 0
        )
    result["application_cpu_ms"] = result["endpoint_cpu_ms"] + result.get("cache_worker_cpu_ms", 0)
    result["non_db_wall_ms"] = result["server_ms"] - result["db_ms"]
    canonical = json.dumps(responses, sort_keys=True, separators=(",", ":"))
    hashes[name].add(hashlib.sha256(canonical.encode()).hexdigest())
    payloads[name] = responses
    return result


def quantile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 4)


emit(
    {
        "kind": "method",
        "n": count,
        "warmups": 10,
        "concurrency": 1,
        "paths": paths,
        "db_ms": "cursor wall time including DB network/driver, not PG CPU",
        "endpoint_cpu_ms": "application endpoint worker thread CPU including ORM/driver; excludes dependency and response serialization CPU",
        "application_cpu_ms": "endpoint CPU plus completed Redis worker CPU; timed-out background commands may finish after the request",
        "non_db_wall_ms": "ASGI wall minus cursor wall; not pure compute",
        "portfolio_pair": "sum of two serial API requests, not parallel browser wall time",
        "first_use": "warm database, not cold disk",
        "workload": "controlled repeated requests; NOT organic traffic hit rate",
        "redis_cold": os.getenv("BENCH_COLD") == "1",
    }
)
with TestClient(TimedApp()) as client:
    for name in paths:
        emit({"kind": "first_use", "name": name, "measurement": run(client, name)})
    for _ in range(10):
        for name in paths:
            run(client, name)
    rng = random.Random(20260906)
    names = list(paths)
    for iteration in range(count):
        rng.shuffle(names)
        for name in names:
            samples[name].append(run(client, name))
        if (iteration + 1) % 100 == 0:
            emit({"kind": "progress", "rounds": iteration + 1})

for name, rows in samples.items():
    metrics = {
        metric: {
            "p50": quantile([r[metric] for r in rows], 0.5),
            "p95": quantile([r[metric] for r in rows], 0.95),
            "p99": quantile([r[metric] for r in rows], 0.99) if len(rows) >= 1000 else None,
        }
        for metric in rows[0]
    }
    emit(
        {
            "kind": "summary",
            "name": name,
            "n": count,
            "metrics": metrics,
            "query_counts": dict(Counter(r["queries"] for r in rows)),
            "hashes": sorted(hashes[name]),
        }
    )
    emit({"kind": "raw", "name": name, "samples": rows})
if "overview" in payloads:
    overview = payloads["overview"][0]
    emit(
        {
            "kind": "overview_equivalence",
            "summary": overview.get("portfolio") == payloads.get("portfolio", [None])[0],
            "analytics": overview.get("analytics") == payloads.get("analytics", [None])[0],
        }
    )

if get_cache:
    cache = get_cache()
    emit(
        {
            "kind": "cache_stats",
            "enabled": cache.enabled,
            "namespace": cache.namespace,
            "stats": cache.stats(),
        }
    )
    if cache.enabled:
        try:
            redis_client = cache.client
            keys = list(redis_client.scan_iter(match=f"{cache.namespace}:*"))
            memory = redis_client.info("memory")
            stats = redis_client.info("stats")
            emit(
                {
                    "kind": "redis_memory",
                    "redis_version": redis_client.info("server")["redis_version"],
                    "keys": len(keys),
                    "key_bytes": sum(redis_client.memory_usage(key) or 0 for key in keys),
                    "used_memory": memory["used_memory"],
                    "used_memory_rss": memory["used_memory_rss"],
                    "evicted_keys": stats["evicted_keys"],
                    "connected_clients": redis_client.info("clients")["connected_clients"],
                }
            )
        except Exception as error:
            emit({"kind": "redis_inspection_unavailable", "error_type": type(error).__name__})
