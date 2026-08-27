"""Replay-session errors. Account failures stay out of the execution kernel."""

from __future__ import annotations


class ReplayError(Exception):
    """Base replay-session failure."""


class ReplayNotFound(ReplayError):
    """Session missing or not owned by the caller."""


class ReplayClosed(ReplayError):
    """Clock / order mutations are refused after close."""


class ReplayLookaheadError(ReplayError):
    """Caller tried to use a time after the session clock."""


class ReplayInsufficientCash(ReplayError):
    """Isolated session cash cannot cover the fill."""


class ReplayInsufficientPosition(ReplayError):
    """Isolated session shares cannot cover the sell."""
