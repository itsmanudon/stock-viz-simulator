/**
 * /trades — full executed-trade history for the current user.
 *
 * The API caps a single response at 500; we render whatever it gives us in
 * reverse-chrono order. If the table outgrows that we'll add a ``?before=ts``
 * cursor on the API.
 */

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listTrades } from "@/lib/api/trading";

function fmtCurrency(raw: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtQty(raw: string): string {
  return Number(raw).toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export default async function TradesPage() {
  const trades = await listTrades(500);

  return (
    <div className="container mx-auto px-6 py-10">
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trade history</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {trades.length} executed trade{trades.length === 1 ? "" : "s"}.
          </p>
        </div>
        {trades.length > 0 && (
          <Button asChild variant="outline" size="sm">
            <a href="/api/export/trades" download="trades.csv">
              Download CSV
            </a>
          </Button>
        )}
      </header>

      {trades.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            You haven't placed any trades yet.{" "}
            <Link href="/trade" className="text-foreground underline">
              Place your first trade →
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead className="w-[120px]">Ticker</TableHead>
                <TableHead className="w-[80px]">Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.map((trade) => {
                const total = Number(trade.quantity) * Number(trade.price);
                return (
                  <TableRow key={trade.id}>
                    <TableCell className="text-muted-foreground">{fmtDate(trade.ts)}</TableCell>
                    <TableCell className="font-mono font-semibold">
                      <Link href={`/stocks/${trade.ticker}`} className="hover:underline">
                        {trade.ticker}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={trade.side === "buy" ? "default" : "secondary"}>
                        {trade.side.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">{fmtQty(trade.quantity)}</TableCell>
                    <TableCell className="text-right font-mono">
                      {fmtCurrency(trade.price)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {fmtCurrency(String(total))}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
