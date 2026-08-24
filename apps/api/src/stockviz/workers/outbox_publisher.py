"""Outbox publisher worker.

Long-running:

    uv --directory apps/api run python -m stockviz.workers.outbox_publisher

One batch (tests / demo):

    uv --directory apps/api run python -m stockviz.workers.outbox_publisher --once
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.outbox import publish_batch
from stockviz.events.producer import ConfluentBrokerPublisher, ensure_event_topics
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True
    logger.info("outbox publisher shutting down")


def run_once(*, publisher: ConfluentBrokerPublisher | None = None) -> int:
    settings = get_settings()
    client = publisher or ConfluentBrokerPublisher(
        bootstrap_servers=settings.kafka_bootstrap_servers
    )
    ensure_event_topics(bootstrap_servers=settings.kafka_bootstrap_servers)
    with Session(engine) as session:
        return publish_batch(session, client, limit=settings.outbox_batch_size)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Publish unpublished outbox events to Kafka.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Publish at most one batch and exit.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    publisher = ConfluentBrokerPublisher(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        if args.once:
            n = run_once(publisher=publisher)
            logger.info("outbox publisher once published=%s", n)
            return 0

        signal.signal(signal.SIGTERM, _request_stop)
        signal.signal(signal.SIGINT, _request_stop)
        ensure_event_topics(bootstrap_servers=settings.kafka_bootstrap_servers)
        while not _stop:
            with Session(engine) as session:
                published = publish_batch(session, publisher, limit=settings.outbox_batch_size)
            if published == 0:
                time.sleep(settings.outbox_poll_interval_seconds)
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
