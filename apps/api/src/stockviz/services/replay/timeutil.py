"""Naive-UTC DB timestamps → aware UTC at the replay adapter boundary.

Mirrors the live trading adapter: naive values are labeled UTC; local-timezone
invention is not performed. Evaluation still never reads the wall clock.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_naive_utc(value: datetime) -> datetime:
    return as_aware_utc(value).replace(tzinfo=None)
