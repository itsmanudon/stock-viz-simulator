"""Broker produce/consume wrappers.

The FastAPI process does not import this module at startup. Workers construct
clients from settings. ``BrokerPublisher`` is a tiny protocol so unit tests
can inject a fake without librdkafka.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class BrokerPublisher(Protocol):
    def publish(self, *, topic: str, key: str, value: dict[str, Any]) -> None:
        """Block until the broker acknowledges the record, then return."""


class BrokerPublishError(RuntimeError):
    """Produce failed or flush did not complete."""


class ConfluentBrokerPublisher:
    """confluent-kafka producer with ``acks=all``.

    Producer idempotence reduces duplicates from broker retries; it is not
    end-to-end exactly-once with the outbox. Crash between ack and
    ``published_at`` still re-produces the row.
    """

    def __init__(self, *, bootstrap_servers: str) -> None:
        from confluent_kafka import Producer

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "acks": "all",
                "enable.idempotence": True,
                "retries": 8,
                "linger.ms": 5,
                "client.id": "stockviz-outbox-publisher",
            }
        )

    def publish(self, *, topic: str, key: str, value: dict[str, Any]) -> None:
        errors: list[str] = []

        def _on_delivery(err: object, _msg: object) -> None:
            if err is not None:
                errors.append(str(err))

        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self._producer.produce(
            topic,
            key=key.encode("utf-8"),
            value=payload,
            on_delivery=_on_delivery,
        )
        remaining = self._producer.flush(15)
        if remaining:
            raise BrokerPublishError(f"flush timed out with {remaining} message(s) in flight")
        if errors:
            raise BrokerPublishError(errors[0])

    def close(self) -> None:
        self._producer.flush(15)


class ConfluentBrokerConsumer:
    """Manual-commit consumer. Offsets are committed by the caller after DB work."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        group_id: str,
        topic: str,
    ) -> None:
        from confluent_kafka import Consumer

        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "client.id": "stockviz-trade-activity-consumer",
            }
        )
        self._consumer.subscribe([topic])

    def poll_json(self, timeout: float) -> tuple[object, dict[str, Any]] | None:
        from confluent_kafka import KafkaError, KafkaException

        msg = self._consumer.poll(timeout)
        if msg is None:
            return None
        err = msg.error()
        if err:
            if err.code() == KafkaError._PARTITION_EOF:
                return None
            raise KafkaException(err)
        raw = msg.value()
        if raw is None:
            raise ValueError("empty Kafka payload")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Kafka payload must be a JSON object")
        logger.info(
            "kafka received topic=%s partition=%s offset=%s key=%s",
            msg.topic(),
            msg.partition(),
            msg.offset(),
            msg.key(),
        )
        return msg, payload

    def commit(self, msg: object) -> None:
        self._consumer.commit(message=msg, asynchronous=False)  # type: ignore[arg-type]

    def close(self) -> None:
        self._consumer.close()


def ensure_trades_topic(*, bootstrap_servers: str, topic: str, partitions: int) -> None:
    """Create the trades topic if it is missing. Safe to call repeatedly."""
    from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    metadata = admin.list_topics(timeout=10)
    if topic in metadata.topics:
        return
    futures = admin.create_topics(
        [NewTopic(topic, num_partitions=partitions, replication_factor=1)]
    )
    for _name, future in futures.items():
        future.result()
    logger.info("created kafka topic %s partitions=%s", topic, partitions)
