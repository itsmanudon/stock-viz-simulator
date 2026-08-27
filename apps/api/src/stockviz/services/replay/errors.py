"""Replay-session errors. Account failures stay out of the execution kernel."""

from __future__ import annotations


class ReplayError(Exception):
    """Base replay-session failure."""


class ReplayNotFound(ReplayError):
    """Session missing or not owned by the caller."""


class ReplayClosed(ReplayError):
    """Mutations are refused after cancel."""


class ReplayCompleted(ReplayError):
    """Mutations are refused after the frozen horizon is exhausted."""


class ReplayLookaheadError(ReplayError):
    """A snapshot after the session clock was presented to the kernel."""


class ReplaySymbolNotFound(ReplayError):
    """Ticker is not in the symbol universe."""


class ReplayRangeError(ReplayError):
    """Requested start/end does not resolve to a usable stored 1d range."""


class ReplayUnsupportedCurrency(ReplayError):
    """Replay trading is USD-only until historical FX exists."""


class ReplayNoMarketError(ReplayError):
    """The session clock does not match a stored bar inside the frozen range."""


class ReplayInsufficientCash(ReplayError):
    """Isolated session cash cannot cover the fill."""


class ReplayInsufficientPosition(ReplayError):
    """Isolated session shares cannot cover the sell."""
