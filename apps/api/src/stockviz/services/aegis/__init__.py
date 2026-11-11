"""Aegis News read sync: client, contract, sync and local reads (Phase 2)."""

from __future__ import annotations

from stockviz.services.aegis.client import AegisClient, AegisError
from stockviz.services.aegis.sync import SyncResult, run_sync

__all__ = ["AegisClient", "AegisError", "SyncResult", "run_sync"]
