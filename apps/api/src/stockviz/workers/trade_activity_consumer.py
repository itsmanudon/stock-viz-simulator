"""Idempotent ``trade.executed`` consumer.

uv --directory apps/api run python -m stockviz.workers.trade_activity_consumer
uv --directory apps/api run python -m stockviz.workers.trade_activity_consumer --once
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.activity import apply_trade_executed
from stockviz.events.contracts import TRADE_ACTIVITY_CONSUMER, TRADES_TOPIC
from stockviz.events.outbox import SchemaIncompatibleError, parse_trade_executed
from stockviz.events.producer import ConfluentBrokerConsumer
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True
    logger.info("trade-activity consumer shutting down")


def process_payload(session: Session, payload: dict) -> str:
    event = parse_trade_executed(payload)
    return apply_trade_executed(session, event, consumer_name=TRADE_ACTIVITY_CONSUMER)


def consume_once(*, timeout: float = 10.0, consumer: ConfluentBrokerConsumer | None = None) -> bool:
    """Poll at most one record. Returns True if a message was handled."""
    settings = get_settings()
    own = consumer is None
    client = consumer or ConfluentBrokerConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topic=settings.kafka_trades_topic or TRADES_TOPIC,
    )
    try:
        polled = client.poll_json(timeout)
        if polled is None:
            return False
        msg, payload = polled
        try:
            with Session(engine) as session:
                result = process_payload(session, payload)
                session.commit()
        except SchemaIncompatibleError:
            logger.exception("incompatible trade.executed payload; offset not committed")
            return True
        client.commit(msg)
        logger.info("kafka offset committed result=%s", result)
        return True
    finally:
        if own:
            client.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Consume stockviz.trades.v1 into derived activity."
    )
    parser.add_argument("--once", action="store_true", help="Handle at most one message and exit.")
    args = parser.parse_args(argv)

    settings = get_settings()
    consumer = ConfluentBrokerConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topic=settings.kafka_trades_topic or TRADES_TOPIC,
    )
    try:
        if args.once:
            consume_once(consumer=consumer)
            return 0
        signal.signal(signal.SIGTERM, _request_stop)
        signal.signal(signal.SIGINT, _request_stop)
        while not _stop:
            polled = consumer.poll_json(1.0)
            if polled is None:
                continue
            msg, payload = polled
            try:
                with Session(engine) as session:
                    process_payload(session, payload)
                    session.commit()
            except SchemaIncompatibleError:
                logger.exception("incompatible payload; leaving offset uncommitted")
                continue
            consumer.commit(msg)
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
