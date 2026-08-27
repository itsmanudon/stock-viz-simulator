"""Isolated ReplaySession + simulation clock (SIM-05).

Replay is not live paper trading. Fills stay off ``trades`` / ``apply_fill`` /
``trade.executed.v1``. The kernel stays pure; this package owns the clock and
the isolated book. Blind historical bar walking is SIM-06.
"""

from stockviz.services.replay.errors import (
    ReplayClosed,
    ReplayError,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayLookaheadError,
    ReplayNotFound,
)
from stockviz.services.replay.session import (
    DEFAULT_REPLAY_CASH,
    ReplaySubmitResult,
    advance_replay_clock,
    close_replay_session,
    create_replay_session,
    get_replay_session,
    list_replay_fills,
    list_replay_positions,
    list_replay_sessions,
    market_snapshot_for_session,
    submit_replay_order,
)

__all__ = [
    "DEFAULT_REPLAY_CASH",
    "ReplayClosed",
    "ReplayError",
    "ReplayInsufficientCash",
    "ReplayInsufficientPosition",
    "ReplayLookaheadError",
    "ReplayNotFound",
    "ReplaySubmitResult",
    "advance_replay_clock",
    "close_replay_session",
    "create_replay_session",
    "get_replay_session",
    "list_replay_fills",
    "list_replay_positions",
    "list_replay_sessions",
    "market_snapshot_for_session",
    "submit_replay_order",
]
