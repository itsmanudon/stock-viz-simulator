"""Shared envelope constants and decimal encoding for Kafka contracts."""

from __future__ import annotations

from decimal import Decimal

SCHEMA_VERSION_V1 = 1


def decimal_str(value: Decimal) -> str:
    """Canonical non-scientific decimal string."""
    return format(value, "f")
