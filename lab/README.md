# lab: the StockViz research node

`lab/` is the research node from the architecture: a small Python package that
runs **on the laptop only**. It reads the Parquet export of the hot database
with DuckDB, so heavy research (factor backtests, forecasts, cross-sectional
scans) runs over the full history without loading the hosted Postgres.

It is not part of the API image or the API's lockfile. It has its own
`pyproject.toml` and `uv.lock` (Python 3.12; `duckdb`, `polars` and `pyarrow`,
pinned) and never imports `stockviz`: the export's directory layout and
`manifest.json` are the contract.

## Never commit exchange data

An export holds exchange and provider data (NSE files, bars, identifiers). It
is never committed, copied into an image or shared. Keep exports under
`lab/data/` (git-ignored) or outside the repository. `*.duckdb` files are
ignored too. `stockviz.cli export-parquet` refuses an `--out` inside the
repository that git would not ignore.

## Getting an export

The transport from the hot node to the laptop is an open owner question
(design note A1, question 3: a private bucket, a volume, or the laptop only).
Until it is answered, run the export locally against a copy of the database:

```bash
# from the repository root, with DATABASE_URL pointing at the copy
uv --directory apps/api run python -m stockviz.cli export-parquet --out ../../lab/data/export
# later, only the months from a date on
uv --directory apps/api run python -m stockviz.cli export-parquet --out ../../lab/data/export --since 2026-11-01
```

Later the hot node runs the same command and the laptop pulls the directory.
It is not in the Railway cron yet.

The layout:

```
export/
  manifest.json                       schema version, export time, source commit,
                                      per partition: rows, bytes, SHA-256, min/max date
  price_bars/year=2025/month=01/part.parquet   daily bars only
  eod_raw/..., eod_extras/..., corporate_actions/..., fundamental_facts/..., fx_rates/...
  instruments/part.parquet            reference tables, whole each run
  instrument_identifiers/part.parquet
  data_files/part.parquet             metadata only; raw files stay in the archive
  intraday_bars/year=2023/month=01/part.parquet   A6.1: minute and hourly bars by month of
                                      the bar's open (ts = open instant, naive UTC; feed, interval)
  intraday_files/part.parquet         A6.1: which file each intraday row came from
```

The owner's intraday files load only into a local Postgres
(`stockviz.cli intraday-load`, which refuses any other database); this lake is
their master copy. Export them with
`export-parquet --out ../../lab/data/export --tables intraday_bars intraday_files`.

Prices are Parquet decimals (`decimal(18,6)` for bars), never floats, and
timestamps are naive UTC as stored. A table with no rows is skipped and listed
under `empty_tables`.

## Commands

```bash
uv run --directory lab lab verify lab/data/export      # every hash and row count; exit 1 on a mismatch
uv run --directory lab lab catalog lab/data/export     # DuckDB views -> lab/data/export/lab.duckdb (or --db)
uv run --directory lab lab query lab/data/export \
  "SELECT ticker, count(*) FROM price_bars GROUP BY 1 ORDER BY 2 DESC"
```

- `verify` recomputes each partition's SHA-256 and row count against the
  manifest and flags files the manifest does not list.
- `catalog` creates or refreshes one view per table,
  `read_parquet('<dir>/<table>/**/*.parquet', hive_partitioning = true)`,
  so dated tables also have integer `year` and `month` columns. It prints each
  table's rows and date range and exits 1 if a count differs from the
  manifest. Views hold absolute paths: after moving an export, run it again.
- `query` runs SQL read-only against the catalogue and prints a small table
  (`--limit` rows, default 50). For real work, open the DuckDB file from
  Python (`duckdb.connect("lab/data/export/lab.duckdb")`) and use Polars.

Run `verify` before `catalog` after every pull.

## Tests

```bash
uv run --directory lab pytest
uv run --directory lab ruff check . && uv run --directory lab ruff format --check .
```

The tests build a tiny export by hand (invented rows, the same layout and
manifest), so they need neither the API nor the network.
