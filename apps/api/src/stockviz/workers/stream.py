"""The intraday stream worker (A6.5): ``python -m stockviz.workers.stream``.

A replay of stored minutes through the worker (local, any evening):

    uv --directory apps/api run python -m stockviz.workers.stream \\
        --replay --from-feed file --symbols TCS --start 2026-01-05 --end 2026-01-10

Its bars are stored as feed ``replayed`` and its firings say "Replayed from
stored bars, not live". ``--speed 60`` replays a minute a second (0, the
default, as fast as it can). ``--no-deliver`` keeps firings in the bell only.

The live stream (``--feed alpaca``, the IEX WebSocket) arrives in A6.6; until
then, and whenever the feed's key is blank, the worker does not start (exit
2) and live widgets show Offline. During A6 the worker runs on the laptop;
nothing on Railway starts it.

Exit codes: 0 done, 1 the stream failed, 2 not available (no key, no
symbols, no stored minutes in the window).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime

from sqlmodel import Session

from stockviz.logging_setup import configure_logging

logger = logging.getLogger(__name__)

SOURCE_FEEDS = ("file", "iex", "sip", "kite")


def _instant(raw: str) -> datetime:
    """``YYYY-MM-DD`` (midnight UTC) or an ISO instant (naive = UTC)."""
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), datetime.min.time(), tzinfo=UTC)
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date or ISO instant: {raw}") from exc
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build intraday bars from a stream and judge alerts.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--replay", action="store_true", help="Replay stored minutes (SimulatedFeed)."
    )
    mode.add_argument("--feed", choices=["alpaca"], help="A live feed (A6.6).")
    p.add_argument("--from-feed", choices=SOURCE_FEEDS, default="file",
                   help="Replay: which stored feed to replay (default file).")  # fmt: skip
    p.add_argument("--symbols", default="", help="Comma-separated tickers (default: watched).")
    p.add_argument("--start", type=_instant, help="Replay: first bar (date or ISO instant).")
    p.add_argument("--end", type=_instant, help="Replay: end, exclusive.")
    p.add_argument("--speed", type=float, default=0.0, help="Replay speed x real time (0 = fast).")
    p.add_argument("--no-deliver", action="store_true", help="Do not drain deliveries on firing.")
    return p


def _tickers(raw: str) -> list[str]:
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def run_replay(args: argparse.Namespace) -> int:
    from stockviz.db import engine
    from stockviz.services.stream.replay import plan_replay, watched
    from stockviz.services.stream.worker import StreamWorker, replay_spec

    if args.start is None or args.end is None or args.end <= args.start:
        print("--replay needs --start and a later --end", file=sys.stderr)
        return 2
    with Session(engine) as session:
        tickers = _tickers(args.symbols) or watched(session)
        if not tickers:
            print("no symbols: name them with --symbols, or add an intraday alert", file=sys.stderr)
            return 2
        plan = plan_replay(
            session, tickers, source_feed=args.from_feed, start=args.start, end=args.end,
            speed=args.speed,
        )  # fmt: skip
    if plan.bars == 0:
        print(f"no stored {args.from_feed} minutes for {', '.join(tickers)} in the window",
              file=sys.stderr)  # fmt: skip
        return 2
    worker = StreamWorker(
        replay_spec(args.from_feed), plan.tickers,
        session_factory=lambda: Session(engine), deliver=not args.no_deliver,
    )  # fmt: skip
    try:
        report = asyncio.run(worker.run(plan.feed.stream(plan.tickers)))
    except Exception:
        logger.exception("the replay stopped")
        return 1
    print(
        f"replayed {', '.join(plan.tickers)} ({args.from_feed}): warm-up {plan.primed} bars, "
        f"{report.ticks} ticks, {report.bars_closed} bars closed, {report.bars_written} written, "
        f"{report.bars_off_session} off-session, {report.bars_judged} alert bars judged, "
        f"{report.fired} fired, {report.delivered} delivered"
    )
    for line in report.skipped:
        print(f"skipped: {line}")
    return 0


def run_live(args: argparse.Namespace) -> int:
    from stockviz.services.feeds.registry import build_feed
    from stockviz.settings import get_settings

    feed = build_feed(args.feed, get_settings())
    if not feed.configured:
        print(f"{args.feed}: not configured (its key is blank); live widgets stay Offline",
              file=sys.stderr)  # fmt: skip
        return 2
    print(f"{args.feed}: the live stream arrives in A6.6; replay with --replay", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parser().parse_args(argv)
    return run_replay(args) if args.replay else run_live(args)


if __name__ == "__main__":
    sys.exit(main())
