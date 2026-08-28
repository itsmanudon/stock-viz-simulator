"""Isolated ReplaySession + simulation clock (SIM-05).

Replay is not live paper trading. Market truth is stored ``PriceBar`` data
clipped to a frozen ticker/start/end. Fills stay off ``trades`` / ``apply_fill``
/ ``trade.executed.v1``.
"""

from stockviz.services.replay.errors import (
    ReplayClosed,
    ReplayCompleted,
    ReplayError,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayJournalLocked,
    ReplayLookaheadError,
    ReplayNoMarketError,
    ReplayNotFound,
    ReplayRangeError,
    ReplaySymbolNotFound,
    ReplayUnsupportedCurrency,
)
from stockviz.services.replay.forensics import (
    ReplayEpisode,
    ReplayForensics,
    compute_replay_forensics,
    compute_replay_forensics_from_rows,
)
from stockviz.services.replay.journal import get_replay_journal, update_replay_journal
from stockviz.services.replay.market import (
    get_next_session_bar,
    get_replay_availability,
    get_session_bar,
    get_visible_replay_history,
    market_snapshot_for_replay,
)
from stockviz.services.replay.session import (
    DEFAULT_REPLAY_CASH,
    ReplaySubmitResult,
    advance_replay_session,
    cancel_replay_session,
    create_replay_session,
    get_replay_session,
    list_replay_fills,
    list_replay_positions,
    list_replay_sessions,
    lock_replay_session,
    session_can_advance,
    submit_replay_order,
)
from stockviz.services.replay.summary import ReplaySummary, compute_replay_summary

__all__ = [
    "DEFAULT_REPLAY_CASH",
    "ReplayClosed",
    "ReplayCompleted",
    "ReplayEpisode",
    "ReplayError",
    "ReplayForensics",
    "ReplayInsufficientCash",
    "ReplayInsufficientPosition",
    "ReplayJournalLocked",
    "ReplayLookaheadError",
    "ReplayNoMarketError",
    "ReplayNotFound",
    "ReplayRangeError",
    "ReplaySubmitResult",
    "ReplaySummary",
    "ReplaySymbolNotFound",
    "ReplayUnsupportedCurrency",
    "advance_replay_session",
    "cancel_replay_session",
    "compute_replay_forensics",
    "compute_replay_forensics_from_rows",
    "compute_replay_summary",
    "create_replay_session",
    "get_next_session_bar",
    "get_replay_availability",
    "get_replay_journal",
    "get_replay_session",
    "get_session_bar",
    "get_visible_replay_history",
    "list_replay_fills",
    "list_replay_positions",
    "list_replay_sessions",
    "lock_replay_session",
    "market_snapshot_for_replay",
    "session_can_advance",
    "submit_replay_order",
    "update_replay_journal",
]
