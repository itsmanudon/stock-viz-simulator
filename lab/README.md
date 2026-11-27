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

## The factor ranker (A9.8, M8.4)

`uv run --directory lab lab rank DIR [--out lab/data/ranker-report.json]`
(`src/stockviz_lab/ranker.py`; LightGBM 4.7.0 and SHAP 0.54.1, lab only,
never in the API image: owner, 27 Nov 2026). It reads the export's daily
`price_bars`.

- **Features** at each month-end, from bars up to that day only:
  - returns over 21, 63, 126 and 252 sessions, and 12-1 momentum;
  - 20- and 60-session volatility;
  - distance from the 252-session high;
  - 20 over 60-session volume.
- **Target:** the cross-sectional percentile of the next 21 sessions' return.
- **Walk-forward:** for each test month, train on the months at least two
  month-ends back (so no label overlaps the test month), 24 at least.
  Parameters are fixed in code, not tuned on the tests.
- **Score:** each test month's Spearman rank IC, then mean, t and hit rate,
  beside 12-1 momentum alone (the baseline the model has to beat).
- **SHAP:** mean |SHAP| per feature from `TreeExplainer` on the last model.
- **Report:** JSON with the monthly ICs, SHAP and the latest month's scores.
  Keep it under `lab/data/` (git-ignored).

First run, 27 Nov 2026, on an export of the 25 seed symbols' daily bars
(2009-2026). There are 173 test months, Oct 2010 to Feb 2025.

| | Mean rank IC | t | Hit rate |
|---|---|---|---|
| LightGBM | +0.016 | 0.94 | 54% |
| 12-1 momentum | +0.024 | 1.00 | 52% |

**No significant edge, and no better than the baseline.** On 25 hand-picked
large caps (survivorship-biased) that is the expected answer. SHAP leaned on
distance from the high, 12-month and 3-month returns.

Tests (`tests/test_ranker.py`, synthetic):
- no feature reads a later bar;
- a planted effect (higher-volatility names drift up faster) is found out of
  sample, with t > 2 and a volatility feature in SHAP's top three;
- pure noise gives no edge.

## Chronos-2 forecast fans (A9.9, M8.1)

`uv run --directory lab lab forecast DIR TICKER ... [--horizon 21]
[--origins 36] [--out lab/data/forecast-report.json]`
(`src/stockviz_lab/forecast.py`; `chronos-forecasting==2.3.2` with `torch`,
lab only, never in the API image).

- **Weights:** `amazon/chronos-2` (Apache-2.0, about 480 MB) download once
  into the Hugging Face cache, outside the repo.
- **Fan:** the 10th, 50th and 90th percentile of the next `horizon` closes,
  from the last 512 closes.
- **Score:** at rolling origins 21 sessions apart, each seeing closes up to
  its origin only.
  - **Coverage:** the share of the 80% band that held (nominal 80%), beside
    a random walk's band from past log returns.
  - **Skill:** 1 - MAE(median) / MAE(last close); above 0 beats a random
    walk.

First run, 27 Nov 2026: 21 sessions ahead, 36 origins per symbol, data to 7
Apr 2025.

| | Coverage | Random-walk coverage | Skill |
|---|---|---|---|
| AAPL | 69% | 81% | -0.032 |
| KO | 75% | 78% | -0.039 |
| NVDA | 69% | 61% | -0.001 |
| JPM | 61% | 75% | -0.019 |

**Chronos-2 does not beat a random walk at one month, and its 80% band is
too narrow on three of the four.** A fan describes a distribution; it is not
a forecast to trade on.

Tests (`tests/test_forecast.py`, fake predictors, no download):
- a calibrated fan covers about 80% with zero skill;
- a narrow fan under-covers;
- the predictor never sees a close after its origin;
- a short history is refused.
