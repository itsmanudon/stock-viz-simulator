/**
 * /markets — sortable, filterable table of all tradeable symbols.
 *
 * Server-rendered. Sort and sector filter come from search params so the URL
 * is shareable and back/forward navigation reflects the current view. Each
 * row also fetches the last 30 closes for a tiny inline sparkline; we
 * Promise.all those so the page renders once.
 */

import Link from "next/link";

import { Sparkline } from "@/components/sparkline";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, getBars, listSymbols } from "@/lib/api";

type SortKey = "ticker" | "change" | "price";
type SortDir = "asc" | "desc";

type Row = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  closes: number[];
  last: number | null;
  changePct: number | null;
};

async function loadRow(
  ticker: string,
  name: string,
  sector: string | null,
  exchange: string | null,
): Promise<Row> {
  try {
    const bars = await getBars(ticker, { limit: 30 });
    const closes = bars.map((b) => Number(b.close));
    const last = closes.length ? closes[closes.length - 1] : null;
    const prev = closes.length > 1 ? closes[closes.length - 2] : null;
    const changePct =
      last !== null && prev !== null && prev !== 0 ? ((last - prev) / prev) * 100 : null;
    return { ticker, name, sector, exchange, closes, last, changePct };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ticker, name, sector, exchange, closes: [], last: null, changePct: null };
    }
    throw err;
  }
}

function fmtPrice(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function compare(rows: Row[], sort: SortKey, dir: SortDir): Row[] {
  const factor = dir === "asc" ? 1 : -1;
  const sorter: Record<SortKey, (a: Row, b: Row) => number> = {
    ticker: (a, b) => a.ticker.localeCompare(b.ticker) * factor,
    change: (a, b) =>
      ((a.changePct ?? Number.NEGATIVE_INFINITY) - (b.changePct ?? Number.NEGATIVE_INFINITY)) *
      factor,
    price: (a, b) =>
      ((a.last ?? Number.NEGATIVE_INFINITY) - (b.last ?? Number.NEGATIVE_INFINITY)) * factor,
  };
  return [...rows].sort(sorter[sort]);
}

function flipDir(current: SortKey | undefined, target: SortKey, dir: SortDir): SortDir {
  if (current !== target) return target === "ticker" ? "asc" : "desc";
  return dir === "asc" ? "desc" : "asc";
}

function sortHref(
  target: SortKey,
  params: { sort?: string; dir?: string; sector?: string },
): string {
  const next = new URLSearchParams();
  next.set("sort", target);
  next.set(
    "dir",
    flipDir(params.sort as SortKey | undefined, target, (params.dir as SortDir) ?? "desc"),
  );
  if (params.sector) next.set("sector", params.sector);
  return `/markets?${next.toString()}`;
}

export default async function MarketsPage({
  searchParams,
}: {
  searchParams: Promise<{ sort?: string; dir?: string; sector?: string }>;
}) {
  const params = await searchParams;
  const sort = (params.sort as SortKey) ?? "ticker";
  const dir = (params.dir as SortDir) ?? (sort === "ticker" ? "asc" : "desc");

  const symbols = await listSymbols({ sector: params.sector });
  const sectors = Array.from(
    new Set((await listSymbols()).map((s) => s.sector).filter((s): s is string => Boolean(s))),
  ).sort();

  const rows = await Promise.all(
    symbols.map((s) => loadRow(s.ticker, s.name, s.sector, s.exchange)),
  );
  const sorted = compare(rows, sort, dir);

  const arrow = (col: SortKey) => (sort === col ? (dir === "asc" ? " ↑" : " ↓") : "");

  return (
    <div className="container mx-auto px-6 py-10">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Markets</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {sorted.length} symbol{sorted.length === 1 ? "" : "s"}
            {params.sector ? ` in ${params.sector}` : ""}
          </p>
        </div>
        <nav className="flex flex-wrap gap-2 text-xs">
          <Link
            href="/markets"
            className={`rounded-md border px-3 py-1.5 transition hover:bg-accent ${
              !params.sector ? "border-primary text-foreground" : "text-muted-foreground"
            }`}
          >
            All
          </Link>
          {sectors.map((sector) => (
            <Link
              key={sector}
              href={`/markets?sector=${encodeURIComponent(sector)}`}
              className={`rounded-md border px-3 py-1.5 transition hover:bg-accent ${
                params.sector === sector
                  ? "border-primary text-foreground"
                  : "text-muted-foreground"
              }`}
            >
              {sector}
            </Link>
          ))}
        </nav>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">
                <Link href={sortHref("ticker", params)} className="hover:text-foreground">
                  Ticker{arrow("ticker")}
                </Link>
              </TableHead>
              <TableHead>Name</TableHead>
              <TableHead className="hidden md:table-cell">Sector</TableHead>
              <TableHead className="hidden md:table-cell">Exchange</TableHead>
              <TableHead className="text-right">
                <Link href={sortHref("price", params)} className="hover:text-foreground">
                  Price{arrow("price")}
                </Link>
              </TableHead>
              <TableHead className="text-right">
                <Link href={sortHref("change", params)} className="hover:text-foreground">
                  1d % {arrow("change")}
                </Link>
              </TableHead>
              <TableHead className="hidden text-right sm:table-cell">30d</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row) => {
              const up = row.changePct !== null && row.changePct >= 0;
              return (
                <TableRow key={row.ticker}>
                  <TableCell className="font-mono font-semibold">
                    <Link href={`/stocks/${row.ticker}`} className="hover:underline">
                      {row.ticker}
                    </Link>
                  </TableCell>
                  <TableCell className="truncate">{row.name}</TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    {row.sector ?? "—"}
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    {row.exchange ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono">${fmtPrice(row.last)}</TableCell>
                  <TableCell
                    className={`text-right font-mono ${
                      row.changePct === null
                        ? "text-muted-foreground"
                        : up
                          ? "text-green-500"
                          : "text-red-500"
                    }`}
                  >
                    {fmtPct(row.changePct)}
                  </TableCell>
                  <TableCell className="hidden text-right sm:table-cell">
                    <Sparkline closes={row.closes} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
