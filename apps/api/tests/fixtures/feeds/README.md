# Feed fixtures (A6.3)

**Hand-written examples, not real market data.** Each file follows the
response shape the provider documents (read 26 Nov 2026; sources in
`apps/api/CLAUDE.md`, "US feeds and the minute backfill"), with invented
prices and volumes. No provider was called to make them, and no key was used.
Never replace them with recorded provider responses or the owner's files.

- `alpaca_bars_page1.json`, `alpaca_bars_page2.json`: single-symbol
  `/v2/stocks/{symbol}/bars`, two pages joined by `next_page_token`;
  nanosecond and plain `Z` timestamps; one bar after the close.
- `alpaca_bars_empty.json`: `bars: null` (no bars in range).
- `tiingo_iex_prices.json`: `/iex/<ticker>/prices` rows, one with a `Z`
  instant and one with a `-05:00` offset (the same instant scheme).
- `tiingo_daily_prices.json`: `/tiingo/daily/<ticker>/prices` rows.
- `tiingo_error.json`, `massive_error.json`: error bodies that echo a fake
  secret, to check it never reaches a message or log.
- `massive_minutes_page1.json`, `massive_minutes_page2.json`:
  `/v2/aggs/.../range/1/minute/...` with `next_url` paging (its `apiKey` is
  stripped by the adapter), a pre-market minute and a fractional volume.
