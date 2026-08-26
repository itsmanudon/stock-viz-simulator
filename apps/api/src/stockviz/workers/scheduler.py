"""Dedicated APScheduler process.

Render still starts the scheduler inside FastAPI when ``ENABLE_SCHEDULER=true``.
Kubernetes API pods keep that flag false and run this module as a singleton:

    python -m stockviz.workers.scheduler

Postgres advisory locks in ``scheduler.py`` remain defense-in-depth if two
copies ever run. Do not use Kafka for scheduler leader election.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading

from stockviz.scheduler import build_scheduler

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    del argv  # argparse-free; this process only runs the in-process scheduler.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    scheduler = build_scheduler()
    stop = threading.Event()

    def _request_stop(_signum: int, _frame: object) -> None:
        logger.info("scheduler received shutdown signal")
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    scheduler.start()
    logger.info("scheduler started; waiting for SIGTERM/SIGINT")
    try:
        while not stop.is_set():
            stop.wait(timeout=1.0)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
