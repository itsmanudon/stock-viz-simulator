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
import { DataTableFrame, NumericCell, SortableHead, TableToolbar } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
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
import {
  type MarketRow,
  type SortDir,
  type SortKey,
  compare,
  fmtPct,
  fmtPrice,
  sortHref,
} from "@/lib/markets-table";
import { cn } from "@/lib/utils";

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

  const rows: MarketRow[] = summary.rows.map((r) => ({
    ticker: r.ticker,
    name: r.name,
    sector: r.sector,
    exchange: r.exchange,
    closes: r.closes.map(Number),
    last: r.last_close === null ? null : Number(r.last_close),
    changePct: r.change_pct,
  }));
  const sorted = compare(rows, sort, dir);

  const sortDirection = (col: SortKey) => (sort === col ? dir : null);

  return (
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <PageHeader
        eyebrow="Markets"
        title="Markets"
        description="End-of-day prices across the tracked universe. Sort any column or filter by sector; the view is captured in the URL."
        meta={
          <>
            {sorted.length} symbol{sorted.length === 1 ? "" : "s"}
            {params.sector ? ` in ${params.sector}` : ""}
          </>
        }
      />

      <div className="mt-6">
        <TableToolbar>
          <nav aria-label="Filter by sector" className="flex flex-wrap gap-2">
            <SectorChip href="/markets" label="All" active={!params.sector} />
            {sectors.map((sector) => (
              <SectorChip
                key={sector}
                href={`/markets?sector=${encodeURIComponent(sector)}`}
                label={sector}
                active={params.sector === sector}
              />
            ))}
          </nav>
        </TableToolbar>

        <DataTableFrame>
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead
                  href={sortHref("ticker", params)}
                  label="Ticker"
                  direction={sortDirection("ticker")}
                  className="w-[120px]"
                />
                <TableHead>Name</TableHead>
                <TableHead className="hidden md:table-cell">Sector</TableHead>
                <TableHead className="hidden md:table-cell">Exchange</TableHead>
                <SortableHead
                  href={sortHref("price", params)}
                  label="Price"
                  direction={sortDirection("price")}
                  align="right"
                />
                <SortableHead
                  href={sortHref("change", params)}
                  label="1d %"
                  direction={sortDirection("change")}
                  align="right"
                />
                <TableHead className="hidden text-right sm:table-cell">30d</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => (
                <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                  <TableCell className="font-mono font-semibold">{row.ticker}</TableCell>
                  <TableCell className="truncate">{row.name}</TableCell>
                  <TableCell className="hidden text-text-tertiary md:table-cell">
                    {row.sector ?? "—"}
                  </TableCell>
                  <TableCell className="hidden text-text-tertiary md:table-cell">
                    {row.exchange ?? "—"}
                  </TableCell>
                  <NumericCell>{row.last === null ? null : `$${fmtPrice(row.last)}`}</NumericCell>
                  <NumericCell signedBy={row.changePct}>
                    {row.changePct === null ? null : fmtPct(row.changePct)}
                  </NumericCell>
                  <TableCell className="hidden text-right sm:table-cell">
                    <Sparkline closes={row.closes} />
                  </TableCell>
                </ClickableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableFrame>
      </div>
    </div>
  );
}

function SectorChip({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      aria-current={active ? "true" : undefined}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition-colors",
        active
          ? "border-brand bg-brand/10 font-medium text-foreground"
          : "border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground",
      )}
    >
      {label}
    </Link>
  );
}
