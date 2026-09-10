"""Shared Kafka consumer loop: poll → handle → DB commit → offset commit.

Domain handlers stay in workers. This module only owns the repeated
infrastructure: poll, dispatch, commit order, backoff, shutdown.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.outbox import SchemaIncompatibleError
from stockviz.events.producer import BrokerConsumer, ConfluentBrokerConsumer
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

Handler = Callable[[Session, dict[str, Any]], str]
ProcessFn = Callable[[dict[str, Any]], str]


def handle_message(
    session: Session,
    payload: dict[str, Any],
    *,
    handlers: dict[str, Handler],
) -> str:
    """Dispatch one payload. Unknown event types are ignored (not errors)."""
    event_type = payload.get("event_type")
    if not isinstance(event_type, str):
        raise SchemaIncompatibleError("payload missing event_type")
    handler = handlers.get(event_type)
    if handler is None:
        logger.info("consumer ignoring event_type=%s", event_type)
        return "ignored"
    return handler(session, payload)


def _rewind(consumer: BrokerConsumer, msg: object) -> None:
    """Put a failed record back at the head of its partition.

    Without this, a handler failure silently drops the record. ``poll()``
    advances the consumer position regardless of commits, so the next poll
    returns the *following* message; if that one succeeds, its commit moves
    the committed offset past the failed record and it is never redelivered.
    For market bars, news, and trade activity that is silent data loss, so we
    rewind and let the same record be retried.

    The consequence is the documented one: a genuinely poison record stalls
    its partition until the code or data is fixed. That is deliberate — this
    pipeline has no dead-letter topic, and for financial data a loud stall
    beats a silent gap. A seek failure must not kill the loop, so it is
    logged and swallowed; the record is then retried after the next
    rebalance or restart.
    """
    try:
        consumer.seek(msg)
    except Exception:
        logger.exception("failed to rewind partition; record may be skipped until restart")


def consume_once(
    *,
    topic: str,
    group_id: str,
    timeout: float,
    backoff_seconds: float,
    consumer: BrokerConsumer | None = None,
    bootstrap_servers: str,
    handlers: dict[str, Handler] | None = None,
    process: ProcessFn | None = None,
) -> bool:
    """Poll at most one record. Returns True if a message was seen.

    ``handlers`` run inside a DB session that this function commits.
    ``process`` runs *outside* a session so the worker can call providers
    before opening a transaction. Exactly one of the two must be set.
    """
    if (process is None) == (handlers is None):
        raise ValueError("provide exactly one of handlers or process")
    own = consumer is None
    client = consumer or ConfluentBrokerConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        topic=topic,
    )
    try:
        polled = client.poll_json(timeout)
        if polled is None:
            return False
        msg, payload = polled
        try:
            if process is not None:
                result = process(payload)
            else:
                with Session(engine) as session:
                    result = handle_message(session, payload, handlers=handlers or {})
                    session.commit()
        except SchemaIncompatibleError:
            logger.exception("incompatible payload; offset not committed, rewinding")
            _rewind(client, msg)
            time.sleep(backoff_seconds)
            return True
        except Exception:
            logger.exception("handler failed; offset not committed, rewinding and backing off")
            _rewind(client, msg)
            time.sleep(backoff_seconds)
            return True
        client.commit(msg)
        logger.info("kafka offset committed result=%s", result)
        return True
    finally:
        if own:
            client.close()


def run_loop(
    *,
    topic: str,
    group_id: str,
    bootstrap_servers: str,
    poll_timeout: float,
    backoff_seconds: float,
    once: bool,
    handlers: dict[str, Handler] | None = None,
    process: ProcessFn | None = None,
) -> int:
    stop = False

    def _request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        logger.info("consumer shutting down topic=%s group=%s", topic, group_id)

    consumer = ConfluentBrokerConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        topic=topic,
    )
    try:
        if once:
            consume_once(
                topic=topic,
                group_id=group_id,
                timeout=max(poll_timeout, 10.0),
                backoff_seconds=backoff_seconds,
                consumer=consumer,
                bootstrap_servers=bootstrap_servers,
                handlers=handlers,
                process=process,
            )
            return 0
        signal.signal(signal.SIGTERM, _request_stop)
        signal.signal(signal.SIGINT, _request_stop)
        while not stop:
            consume_once(
                topic=topic,
                group_id=group_id,
                timeout=poll_timeout,
                backoff_seconds=backoff_seconds,
                consumer=consumer,
                bootstrap_servers=bootstrap_servers,
                handlers=handlers,
                process=process,
            )
    finally:
        consumer.close()
    return 0


def worker_main(
    *,
    description: str,
    topic: str,
    group_id: str,
    argv: list[str] | None,
    handlers: dict[str, Handler] | None = None,
    process: ProcessFn | None = None,
) -> int:
    """Argparse + settings bootstrap shared by Kafka workers."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--once", action="store_true", help="Handle at most one message and exit.")
    args = parser.parse_args(argv)
    settings = get_settings()
    return run_loop(
        topic=topic,
        group_id=group_id,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        poll_timeout=settings.kafka_poll_timeout_seconds,
        backoff_seconds=settings.kafka_retry_backoff_seconds,
        once=args.once,
        handlers=handlers,
        process=process,
    )
