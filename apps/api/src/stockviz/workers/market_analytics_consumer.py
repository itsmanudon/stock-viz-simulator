"""Consume ``market.bars.refreshed``: ticker-scoped metrics + alerts.

uv --directory apps/api run python -m stockviz.workers.market_analytics_consumer --once
"""

from __future__ import annotations

import sys
from typing import Any

from sqlmodel import Session

from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    MARKET_ANALYTICS_CONSUMER,
    MARKET_TOPIC,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import apply_market_bars_refreshed
from stockviz.events.outbox import parse_market_bars_refreshed


def handle_bars_refreshed(session: Session, payload: dict[str, Any]) -> str:
    event = parse_market_bars_refreshed(payload)
    return apply_market_bars_refreshed(session, event)


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.market.v1 market.bars.refreshed.",
        topic=MARKET_TOPIC,
        group_id=MARKET_ANALYTICS_CONSUMER,
        argv=argv,
        handlers={EVENT_TYPE_MARKET_BARS_REFRESHED: handle_bars_refreshed},
    )


if __name__ == "__main__":
    sys.exit(main())
