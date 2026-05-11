"""Service layer.

Modules under ``services/ingest/`` write to the DB from external sources.
Top-level service modules (``symbols``, ``bars``, ``news``, ``quotes``) read
from the DB for the routers. Keeping ingest and read-side separate makes the
boundary between scheduled writes and per-request reads obvious.
"""
