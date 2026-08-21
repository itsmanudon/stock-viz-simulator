/**
 * /markets — sortable, filterable table of all tradeable symbols.
 *
 * Server-rendered. Sort and sector filter come from search params so the URL
 * is shareable and back/forward navigation reflects the current view.
 *
 * The whole page is one call to `/v1/markets/summary`: rows, last close, day
 * change, sparkline series, and the sector list. It previously issued two
 * `listSymbols` calls plus one `getBars` per symbol — 34 requests for a
 * 32-symbol universe, all `no-store`, against a 60/minute rate limit.
 */

import Link from "next/link";

import { ClickableRow } from "@/components/clickable-row";
import { Sparkline } from "@/components/sparkline";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getMarketsSummary } from "@/lib/api";

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

  const summary = await getMarketsSummary({ sector: params.sector, sparklineDays: 30 });
  const sectors = summary.sectors;

  const rows: Row[] = summary.rows.map((r) => ({
    ticker: r.ticker,
    name: r.name,
    sector: r.sector,
    exchange: r.exchange,
    closes: r.closes.map(Number),
    last: r.last_close === null ? null : Number(r.last_close),
    changePct: r.change_pct,
  }));
  const sorted = compare(rows, sort, dir);

  const arrow = (col: SortKey) => (sort === col ? (dir === "asc" ? " ↑" : " ↓") : "");

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
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
                <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                  <TableCell className="font-mono font-semibold">{row.ticker}</TableCell>
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
                </ClickableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
