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

import type { Metadata } from "next";
import Link from "next/link";

import { ClickableRow } from "@/components/clickable-row";
import { DataTableFrame, NumericCell, SortableHead, TableToolbar } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Sparkline } from "@/components/sparkline";
import { CardSortBar, type SymbolCardData, SymbolCardList } from "@/components/symbol-card-list";
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
  fmtMoney,
  fmtPct,
  sortHref,
} from "@/lib/markets-table";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Markets" };

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
    currency: r.currency,
    closes: r.closes.map(Number),
    last: r.last_close === null ? null : Number(r.last_close),
    lastAt: r.last_close_at,
    changePct: r.change_pct,
  }));
  // Every price is a stored close; say which (UI audit T1). Symbols can end on
  // different days, so each row carries its own date and the header names the
  // most recent one.
  const latestAt = rows
    .map((row) => row.lastAt?.slice(0, 10) ?? "")
    .reduce((a, b) => (b > a ? b : a), "");
  const latestLabel = formatCloseDate(latestAt);
  const sorted = compare(rows, sort, dir);
  // Sector and exchange come from `stockviz.cli metadata`. Without it every
  // cell was a dash (UI audit S3), so a column with no values is left out.
  const hasSector = rows.some((row) => row.sector);
  const hasExchange = rows.some((row) => row.exchange);

  const sortDirection = (col: SortKey) => (sort === col ? dir : null);

  const cardRows: SymbolCardData[] = sorted.map((row) => ({
    ticker: row.ticker,
    name: row.name,
    price: row.last === null ? null : fmtMoney(row.last, row.currency),
    changePct: row.changePct,
    changeLabel: row.changePct === null ? null : fmtPct(row.changePct),
    // Only surface classification the symbol actually has; a row of em
    // dashes costs vertical space on a phone and says nothing.
    metrics: [
      // A symbol without stored bars says so instead of showing bare dashes
      // (UI audit S2).
      row.last === null
        ? { label: "Price", value: "No stored history" }
        : { label: "Close", value: formatCloseDate(row.lastAt) ?? "Date unknown" },
      ...(row.sector ? [{ label: "Sector", value: row.sector }] : []),
      ...(row.exchange ? [{ label: "Exchange", value: row.exchange }] : []),
    ],
    visual:
      row.closes.length > 1 ? (
        <Sparkline
          closes={row.closes}
          width={280}
          height={40}
          className="w-full"
          periodLabel="30-day"
        />
      ) : null,
  }));

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Markets"
        title="Markets"
        description="Stored end-of-day closes across the tracked universe, not live quotes. Sort any column or filter by sector; the view is captured in the URL."
        meta={
          <>
            {sorted.length} symbol{sorted.length === 1 ? "" : "s"}
            {params.sector ? ` in ${params.sector}` : ""}
            {latestLabel ? ` · latest close ${latestLabel}` : ""}
          </>
        }
      />

      <div className="mt-5">
        <TableToolbar>
          <nav aria-label="Filter by sector" className="flex max-w-full flex-wrap gap-1.5">
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

        {/* Cards below lg, table above.
            Measured against real data, the full column set is 891px wide
            (Sector alone is 183px — "Communication Services"). The content box
            is ~720px at md and ~752px at lg, because the sidebar claims 224px
            from lg up. So the switch is lg, and Sector and Exchange both wait
            for xl: that leaves 627px at lg and the full 891px inside the 992px
            available at xl. */}
        <div className="lg:hidden">
          <CardSortBar
            options={[
              { key: "ticker", label: "Ticker", href: sortHref("ticker", params) },
              { key: "price", label: "Price", href: sortHref("price", params) },
              { key: "change", label: "1d %", href: sortHref("change", params) },
            ]}
            activeKey={sort}
            direction={dir}
          />
          <SymbolCardList className="mt-3" rows={cardRows} />
        </div>

        <DataTableFrame className="hidden lg:block">
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
                {hasSector ? <TableHead className="hidden xl:table-cell">Sector</TableHead> : null}
                {hasExchange ? (
                  <TableHead className="hidden xl:table-cell">Exchange</TableHead>
                ) : null}
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
                <TableHead className="hidden text-right lg:table-cell">30d</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => (
                <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                  <TableCell className="font-mono font-semibold">{row.ticker}</TableCell>
                  <TableCell className="truncate">
                    {row.name}
                    {row.last === null ? (
                      <span className="ml-2 rounded-full border border-border-muted px-2 py-0.5 text-2xs text-text-tertiary">
                        No stored history
                      </span>
                    ) : null}
                  </TableCell>
                  {hasSector ? (
                    <TableCell className="hidden text-text-tertiary xl:table-cell">
                      {row.sector ?? "—"}
                    </TableCell>
                  ) : null}
                  {hasExchange ? (
                    <TableCell className="hidden text-text-tertiary xl:table-cell">
                      {row.exchange ?? "—"}
                    </TableCell>
                  ) : null}
                  <NumericCell>
                    {row.last === null ? null : (
                      <>
                        {fmtMoney(row.last, row.currency)}
                        <span className="block text-2xs text-text-tertiary">
                          {formatCloseDate(row.lastAt)}
                        </span>
                      </>
                    )}
                  </NumericCell>
                  <NumericCell signedBy={row.changePct}>
                    {row.changePct === null ? null : fmtPct(row.changePct)}
                  </NumericCell>
                  <TableCell className="hidden text-right lg:table-cell">
                    <Sparkline closes={row.closes} periodLabel="30-day" />
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
        "rounded-md border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-primary bg-primary font-semibold text-primary-foreground"
          : "border-border-muted text-text-secondary hover:bg-surface-hover hover:text-foreground",
      )}
    >
      {label}
    </Link>
  );
}
