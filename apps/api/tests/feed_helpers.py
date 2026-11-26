"""Fake HTTP and clocks for the A6.3 feed tests. No provider is ever called."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def response(status: int, body: bytes | object, headers: dict[str, str] | None = None):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return httpx.Response(status, content=content, headers=headers or {})


@dataclass
class FakeHttp:
    """Answers each GET with the next queued response and records the call."""

    queue: list  # httpx.Response | Exception, answered in order
    calls: list[tuple[str, dict[str, str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, url: str, params: dict[str, str], headers: dict[str, str]):
        self.calls.append((url, dict(params), dict(headers)))
        if not self.queue:
            raise AssertionError(f"unexpected request to {url}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class FakeClock:
    """A monotonic clock that only moves when ``sleep`` is called."""

    now: float = 1_000.0
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
