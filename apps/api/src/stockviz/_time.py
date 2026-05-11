"""Time helpers.

The DB columns are ``TIMESTAMP`` (no tz). We standardize on naive UTC at the
Python boundary: take the tz-aware ``datetime.now(UTC)`` and strip the tz info
before persistence. ``datetime.utcnow()`` is deprecated in 3.12.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC datetime — drop-in replacement for the deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)
