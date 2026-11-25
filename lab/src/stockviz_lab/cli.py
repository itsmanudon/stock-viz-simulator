"""``lab verify | catalog | query`` over a Parquet export.

uv run --directory lab lab verify DIR
uv run --directory lab lab catalog DIR [--db FILE]
uv run --directory lab lab query DIR "SELECT ..." [--db FILE] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import polars as pl

from stockviz_lab.catalog import build_catalog, run_query
from stockviz_lab.manifest import ManifestError, verify


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify(Path(args.dir))
    for problem in report.problems:
        print(f"MISMATCH {problem}")
    print(
        f"{report.partitions} partition(s), {report.rows} rows checked: "
        + ("ok" if report.ok else f"{len(report.problems)} problem(s)")
    )
    return 0 if report.ok else 1


def _cmd_catalog(args: argparse.Namespace) -> int:
    rows = build_catalog(Path(args.dir), Path(args.db) if args.db else None)
    width = max((len(r.table) for r in rows), default=5)
    print(f"{'table':<{width}}  {'rows':>10}  date range")
    for r in rows:
        span = f"{r.min_date} .. {r.max_date}" if r.min_date else "-"
        flag = "" if r.ok else f"  (manifest says {r.manifest_rows})"
        print(f"{r.table:<{width}}  {r.rows:>10}  {span}{flag}")
    return 0 if all(r.ok for r in rows) else 1


def _cmd_query(args: argparse.Namespace) -> int:
    frame = run_query(Path(args.dir), args.sql, Path(args.db) if args.db else None)
    with pl.Config(tbl_rows=args.limit, tbl_cols=-1, fmt_str_lengths=40):
        print(frame)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify", help="Check partition hashes and row counts")
    p_verify.add_argument("dir")
    p_verify.set_defaults(fn=_cmd_verify)

    p_catalog = sub.add_parser("catalog", help="Create or refresh the DuckDB views")
    p_catalog.add_argument("dir")
    p_catalog.add_argument("--db", default=None, help="Default: DIR/lab.duckdb")
    p_catalog.set_defaults(fn=_cmd_catalog)

    p_query = sub.add_parser("query", help="Run a SQL query and print a small table")
    p_query.add_argument("dir")
    p_query.add_argument("sql")
    p_query.add_argument("--db", default=None, help="Default: DIR/lab.duckdb")
    p_query.add_argument("--limit", type=int, default=50, help="Rows to print")
    p_query.set_defaults(fn=_cmd_query)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, FileNotFoundError, duckdb.Error) as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
