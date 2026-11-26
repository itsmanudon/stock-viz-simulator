"""Broker tradebook imports (A5.3, M10.2 CSV part).

- ``columns``: the ``zerodha_tradebook_v1`` column map (unconfirmed).
- ``parse``: the CSV into typed rows; dates, numbers, segments.
- ``engine``: the holdings-only ledger as a pure function (positions,
  realised P&L, splits, estimated fees, basis checks).
- ``book``: preview, commit, rebuild, batch delete and opening lots.
"""
