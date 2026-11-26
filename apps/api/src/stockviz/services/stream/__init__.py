"""The intraday stream worker (A6.5): workspace ``docs/a6-design-note.md``.

- ``bars``: one-minute bars from ticks, in memory.
- ``worker``: the loop (store, ``NOTIFY``, judge, deliver, status).
- ``hub``: ``NOTIFY`` on the worker side; ``LISTEN`` and server-sent events
  fan-out on the API side.
- ``replay``: the ``SimulatedFeed`` replay (warm-up, symbols, the window).
"""
