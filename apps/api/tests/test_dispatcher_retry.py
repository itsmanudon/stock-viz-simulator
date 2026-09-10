"""A failed record must be retried, not silently skipped.

``poll()`` advances the consumer position whether or not the offset was
committed. Before the rewind in ``dispatcher._rewind``, a handler failure
therefore dropped the record: the next poll returned the *following* message,
and its commit moved the committed offset past the failed one for good. These
tests model that position/commit split so the regression cannot come back.
"""

from __future__ import annotations

import pytest

from stockviz.events.dispatcher import consume_once
from stockviz.events.outbox import SchemaIncompatibleError

TOPIC = "stockviz.market.v1"
GROUP = "test-group"


class FakeMessage:
    def __init__(self, topic: str, partition: int, offset: int) -> None:
        self._topic = topic
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset


class FakeConsumer:
    """Models librdkafka's position/commit split.

    ``poll_json`` hands back the record at ``position`` and advances it, the
    way a real consumer does. Only ``seek`` moves the position backwards, and
    ``commit`` records ``offset + 1`` — so a test can observe a committed
    offset jumping over a record that was never handled.
    """

    def __init__(self, payloads: list[dict], *, partition: int = 0) -> None:
        self._messages = [
            (FakeMessage(TOPIC, partition, offset), payload)
            for offset, payload in enumerate(payloads)
        ]
        self.position = 0
        self.committed: list[int] = []
        self.seeks: list[int] = []
        self.closed = False

    def poll_json(self, timeout: float):
        if self.position >= len(self._messages):
            return None
        msg, payload = self._messages[self.position]
        self.position += 1
        return msg, payload

    def commit(self, msg) -> None:
        self.committed.append(msg.offset() + 1)

    def seek(self, msg) -> None:
        self.seeks.append(msg.offset())
        self.position = msg.offset()

    def close(self) -> None:
        self.closed = True


def _consume(consumer: FakeConsumer, process) -> bool:
    return consume_once(
        topic=TOPIC,
        group_id=GROUP,
        timeout=0.01,
        backoff_seconds=0.0,
        consumer=consumer,
        bootstrap_servers="unused:9092",
        process=process,
    )


def test_successful_record_commits_and_does_not_rewind() -> None:
    consumer = FakeConsumer([{"event_type": "market.refresh.requested"}])

    assert _consume(consumer, lambda _payload: "applied") is True
    assert consumer.committed == [1]
    assert consumer.seeks == []


def test_handler_failure_rewinds_and_does_not_commit() -> None:
    consumer = FakeConsumer([{"event_type": "market.refresh.requested"}])

    def _boom(_payload: dict) -> str:
        raise RuntimeError("provider timed out")

    assert _consume(consumer, _boom) is True
    assert consumer.committed == []
    assert consumer.seeks == [0]
    # Position rewound, so the same record is what the next poll returns.
    assert consumer.position == 0


def test_schema_incompatible_record_rewinds_and_stalls_its_partition() -> None:
    """No dead-letter topic exists, so a poison record must stall, not vanish."""
    consumer = FakeConsumer([{"event_type": "market.refresh.requested"}])

    def _bad_schema(_payload: dict) -> str:
        raise SchemaIncompatibleError("unsupported schema_version 99")

    for _ in range(3):
        _consume(consumer, _bad_schema)

    assert consumer.committed == []
    assert consumer.seeks == [0, 0, 0]


def test_transient_failure_retries_the_same_record_before_moving_on() -> None:
    """The regression: a failed record must not be skipped by the next commit."""
    consumer = FakeConsumer(
        [
            {"event_type": "market.refresh.requested", "n": 0},
            {"event_type": "market.refresh.requested", "n": 1},
        ]
    )
    seen: list[int] = []
    attempts = {"count": 0}

    def _flaky(payload: dict) -> str:
        seen.append(payload["n"])
        if payload["n"] == 0 and attempts["count"] == 0:
            attempts["count"] += 1
            raise RuntimeError("transient provider error")
        return "applied"

    for _ in range(3):
        _consume(consumer, _flaky)

    # Record 0 was retried and committed before record 1 was ever handled.
    assert seen == [0, 0, 1]
    assert consumer.committed == [1, 2]


def test_rewind_failure_is_swallowed_so_the_loop_survives() -> None:
    """A broken seek must not kill the worker; it degrades to the old skip."""

    class UnseekableConsumer(FakeConsumer):
        def seek(self, msg) -> None:
            raise RuntimeError("no assignment for partition")

    consumer = UnseekableConsumer([{"event_type": "market.refresh.requested"}])

    def _boom(_payload: dict) -> str:
        raise RuntimeError("provider timed out")

    assert _consume(consumer, _boom) is True
    assert consumer.committed == []


def test_empty_poll_returns_false() -> None:
    consumer = FakeConsumer([])
    assert _consume(consumer, lambda _payload: "applied") is False


def test_requires_exactly_one_of_handlers_or_process() -> None:
    with pytest.raises(ValueError):
        consume_once(
            topic=TOPIC,
            group_id=GROUP,
            timeout=0.01,
            backoff_seconds=0.0,
            consumer=FakeConsumer([]),
            bootstrap_servers="unused:9092",
        )
