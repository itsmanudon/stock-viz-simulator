/**
 * /trades — full executed-trade history for the current user.
 *
 * The API caps a single response at 500; we render whatever it gives us in
 * reverse-chrono order. If the table outgrows that we'll add a ``?before=ts``
 * cursor on the API.
 *
 * Each trade is in its symbol's own currency (price and total), and times
 * are UTC with the zone named. Realized P&L is the one USD figure: the API
 * computes it in USD against the weighted-average cost.
 */

import { BookLink as Link } from "@/components/book-link";
import type { Metadata } from "next";

import { DataTableFrame, NumericCell } from "@/components/data-table";
import { FigureStrip } from "@/components/figure-strip";
import { OrderSideBadge } from "@/components/operational-page-header";
import { MetaChip, PageEmptyState, PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatUtcDateTime } from "@/lib/api-time";
import { listTrades } from "@/lib/api/trading";
import { loadBookContext } from "@/lib/book-context";
import { formatCurrency, formatSignedCurrency } from "@/lib/portfolio-view-model";

export const metadata: Metadata = { title: "Trade history" };

function fmtQty(raw: string): string {
  return Number(raw).toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export default async function TradesPage({
  searchParams,
}: {
  searchParams: Promise<{ book?: string }>;
}) {
  const params = await searchParams;
  // A5.2: one book's fills, or every book's (`?book=all`, each row names its book).
  const books = await loadBookContext(params.book, "/trades", params);
  const trades = await listTrades(500, books.book);
  const bookName = new Map(books.books.map((b) => [b.id, b.name]));
  const sells = trades.filter((trade) => trade.realized_pnl !== null);
  const winningSells = sells.filter((trade) => Number(trade.realized_pnl) > 0).length;
  const buys = trades.filter((trade) => trade.side === "buy").length;
  const grossRealized = sells.reduce((sum, trade) => sum + Number(trade.realized_pnl), 0);
  // A4.2, net first: realized P&L less every fee paid on the listed fills
  // (buys too), each at its fill's rate into the base currency. Fills from
  // before A4.2 carry no fee and add nothing.
  const feesPaid = trades.reduce(
    (sum, trade) => sum + Number(trade.fees ?? 0) * Number(trade.fx_rate ?? 1),
    0,
  );
  const realized = grossRealized - feesPaid;
  // Realized P&L is in the account's base currency (Phase 4.8). All books
  // may mix currencies: then it is not totalled (each book's page has it).
  const baseCurrency = trades[0]?.base_currency ?? "USD";
  const oneCurrency = trades.every((trade) => (trade.base_currency ?? "USD") === baseCurrency);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:py-7">
      <PageHeader
        title="Trade history"
        description="Every executed paper trade, newest first. Prices are in each symbol's own currency."
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {trades.length} executed trade{trades.length === 1 ? "" : "s"}
            </span>
            <MetaChip>
              {books.isAll ? "All books" : `Book: ${books.selected?.name ?? "Default"}`}
            </MetaChip>
            <MetaChip>Times in UTC</MetaChip>
          </span>
        }
        actions={
          trades.length > 0 ? (
            <Button asChild variant="outline" size="sm" className="rounded-full">
              <a
                href={`/api/export/trades${books.book != null ? `?book=${books.book}` : ""}`}
                download="trades.csv"
              >
                Download CSV
              </a>
            </Button>
          ) : null
        }
      />

      {trades.length === 0 ? (
        <div className="mt-6">
          <PageEmptyState
            title="No trades yet"
            action={
              <Link href="/trade" className="text-sm font-medium hover:underline">
                Place your first trade →
              </Link>
            }
          >
            <p>Fills from the trade ticket and from filled orders appear here.</p>
          </PageEmptyState>
        </div>
      ) : (
        <>
          {/* Realized P&L can be totalled because the API reports it in USD
              for every sell; prices and totals stay per row, in each
              symbol's currency, and are never added up. */}
          <FigureStrip
            label="Trade summary"
            className="mt-5"
            figures={[
              { label: "Trades", value: String(trades.length), note: "latest 500 at most" },
              ...(sells.length > 0 && !oneCurrency
                ? [
                    {
                      label: "Realized P&L",
                      value: "Per book",
                      note: "these books hold different currencies; open one book to total it",
                    },
                  ]
                : []),
              ...(sells.length > 0 && oneCurrency
                ? [
                    {
                      label: "Realized P&L",
                      value: (
                        <span
                          className={
                            realized > 0
                              ? "text-positive"
                              : realized < 0
                                ? "text-negative"
                                : undefined
                          }
                        >
                          {realized === 0 ? null : (
                            <span aria-hidden>{realized > 0 ? "▲ " : "▼ "}</span>
                          )}
                          {formatSignedCurrency(realized, baseCurrency)}
                        </span>
                      ),
                      note:
                        feesPaid > 0
                          ? `after ${formatCurrency(String(feesPaid), baseCurrency)} of fees · gross ${formatSignedCurrency(grossRealized, baseCurrency)}`
                          : "after fees, all sells listed",
                    },
                  ]
                : []),
              { label: "Buys", value: String(buys) },
              { label: "Sells", value: String(trades.length - buys) },
              ...(sells.length > 0
                ? [
                    {
                      label: "Sells at a gain",
                      value: `${winningSells} of ${sells.length}`,
                      note: "against average cost",
                    },
                  ]
                : []),
            ]}
          />

          <DataTableFrame className="mt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="hidden sm:table-cell">Time (UTC)</TableHead>
                  <TableHead className="w-[100px] md:w-[120px]">Ticker</TableHead>
                  <TableHead className="w-[72px] md:w-[88px]">Side</TableHead>
                  {books.isAll ? (
                    <TableHead className="hidden md:table-cell">Book</TableHead>
                  ) : null}
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="hidden text-right md:table-cell">Price</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">
                    Realized P&amp;L, Net
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade) => (
                  <TableRow key={trade.id}>
                    <TableCell className="hidden text-text-tertiary sm:table-cell">
                      {formatUtcDateTime(trade.ts)}
                    </TableCell>
                    <TableCell className="ticker font-semibold">
                      <Link href={`/stocks/${trade.ticker}`} className="hover:underline">
                        {trade.ticker}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <OrderSideBadge side={trade.side} />
                    </TableCell>
                    {books.isAll ? (
                      <TableCell className="hidden text-xs text-text-secondary md:table-cell">
                        {(trade.book_id != null && bookName.get(trade.book_id)) || "—"}
                      </TableCell>
                    ) : null}
                    <TableCell className="text-right font-mono">{fmtQty(trade.quantity)}</TableCell>
                    <TableCell className="hidden text-right font-mono md:table-cell">
                      {formatCurrency(trade.price, trade.currency)}
                    </TableCell>
                    {/* Net first: what the fill cost or paid after its fees. */}
                    <TableCell className="text-right font-mono">
                      {formatCurrency(trade.net_native ?? trade.total_native, trade.currency)}
                      {trade.fees != null && Number(trade.fees) > 0 ? (
                        <span
                          className="block text-2xs text-text-tertiary"
                          data-testid="trade-fees"
                          title={(trade.fee_lines ?? [])
                            .map((line) => `${line.label} ${line.amount}`)
                            .join(", ")}
                        >
                          {formatCurrency(trade.total_native, trade.currency)}{" "}
                          {trade.side === "buy" ? "+" : "−"} fees{" "}
                          {formatCurrency(trade.fees, trade.currency)}
                        </span>
                      ) : null}
                    </TableCell>
                    {/* Only sells realize a gain or loss; a buy shows an em dash. */}
                    <NumericCell
                      signedBy={
                        trade.realized_pnl === null
                          ? null
                          : Number(trade.realized_pnl_net ?? trade.realized_pnl)
                      }
                      className="hidden sm:table-cell"
                    >
                      {trade.realized_pnl === null ? null : (
                        <>
                          {formatSignedCurrency(
                            trade.realized_pnl_net ?? trade.realized_pnl,
                            trade.base_currency ?? "USD",
                          )}
                          {trade.realized_pnl_net != null ? (
                            <span className="block text-2xs text-text-tertiary">
                              gross{" "}
                              {formatSignedCurrency(
                                trade.realized_pnl,
                                trade.base_currency ?? "USD",
                              )}
                            </span>
                          ) : null}
                        </>
                      )}
                    </NumericCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataTableFrame>
        </>
      )}
    </div>
  );
}
