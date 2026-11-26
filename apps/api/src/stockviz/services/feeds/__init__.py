"""A6.3 feeds and brokers (M1.6): workspace ``docs/a6-design-note.md``.

- ``base``: ``FeedProvider`` / ``BrokerProvider`` protocols, ``FeedBar``,
  ``Tick``, ``Capabilities``, classified errors, ``reconnecting`` (stream
  backoff), ``us_symbol``.
- ``ratelimit``: token buckets from the documented limits (fake clock in tests).
- ``http``: the one HTTP edge (classification, 429 retries, fixed messages).
- ``simulated``: ``SimulatedFeed``, stored minutes replayed as "Replayed".
- ``alpaca``, ``tiingo``, ``massive``: free-plan history adapters;
  ``finnhub``: stream-only stub (candles are premium).
- ``registry``: providers by name from settings; ``backfill``: the
  ``intraday-backfill`` plan and writer; ``status``: ``/v1/broker/feeds``.
"""
