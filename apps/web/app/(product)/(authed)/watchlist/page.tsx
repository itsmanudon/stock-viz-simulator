/**
 * /watchlist — symbols the user has starred.
 *
 * Server-rendered. Each row shows latest close + a 30-day sparkline; clicking
 * the row deep-links to /stocks/[ticker]. The "remove" button posts to the
 * shared toggleWatchlistAction.
 */

import Link from "next/link";

import { Sparkline } from "@/components/sparkline";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getBars } from "@/lib/api/bars";
import { listWatchlist } from "@/lib/api/watchlist";

import { WatchlistToggle } from "@/components/watchlist-toggle";

function fmtCurrency(raw: string | null): string {
  if (raw === null) return "—";
  const n = Number(raw);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default async function WatchlistPage() {
  const items = await listWatchlist();

  // Fetch 30-day sparkline bars in parallel.
  const sparklines = await Promise.all(
    items.map((item) =>
      getBars(item.ticker, { limit: 30 })
        .then((bars) => bars.map((b) => Number(b.close)))
        .catch(() => [] as number[]),
    ),
  );

  return (
    <div className="container mx-auto px-6 py-10">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Watchlist</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {items.length} symbol{items.length === 1 ? "" : "s"}. Add or remove from any stock page.
        </p>
      </header>

      {items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Your watchlist is empty.{" "}
            <Link href="/markets" className="text-foreground underline">
              Browse markets →
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[120px]">Ticker</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead className="text-right">Last close</TableHead>
                <TableHead className="w-[120px]">30-day</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="w-[180px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item, i) => (
                <TableRow key={item.ticker}>
                  <TableCell className="font-mono font-semibold">
                    <Link href={`/stocks/${item.ticker}`} className="hover:underline">
                      {item.ticker}
                    </Link>
                  </TableCell>
                  <TableCell className="truncate text-muted-foreground">{item.name}</TableCell>
                  <TableCell className="text-muted-foreground">{item.sector ?? "—"}</TableCell>
                  <TableCell className="text-right font-mono">
                    {fmtCurrency(item.last_close)}
                  </TableCell>
                  <TableCell>
                    <Sparkline closes={sparklines[i] ?? []} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {fmtDate(item.added_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <WatchlistToggle ticker={item.ticker} initialInWatchlist={true} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
