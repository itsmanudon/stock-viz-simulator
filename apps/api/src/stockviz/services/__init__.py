"""Service layer.

Modules under ``services/ingest/`` write to the DB from external sources.
Top-level service modules (``metrics``, ``screener``, ``event_study`` ...)
read from the DB for the routers; ``aegis/`` copies Aegis News in and reads it
back. Keeping ingest and read-side separate makes the
boundary between scheduled writes and per-request reads obvious.
"""
