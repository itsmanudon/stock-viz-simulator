/**
 * /orders — pending and historical advanced orders (limit, stop-loss, take-profit).
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
import { type OrderStatus, listOrders } from "@/lib/api/trading";
import { cancelOrderAction } from "./actions";

function fmtCurrency(raw: string | null): string {
  if (raw === null) return "—";
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
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

function statusBadge(status: OrderStatus) {
  const map: Record<OrderStatus, "default" | "secondary" | "destructive"> = {
    pending: "default",
    filled: "secondary",
    cancelled: "destructive",
  };
  return <Badge variant={map[status]}>{status}</Badge>;
}

function orderTypeLabel(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default async function OrdersPage() {
  const orders = await listOrders();
  const pending = orders.filter((o) => o.status === "pending");
  const history = orders.filter((o) => o.status !== "pending");

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Pending orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Limit, stop-loss, and take-profit orders. Settled against EOD close each weekday.
        </p>
      </header>

      {/* Pending orders */}
      {pending.length === 0 ? (
        <Card className="mb-8">
          <CardContent className="p-6 text-sm text-muted-foreground">
            No pending orders.{" "}
            <Link href="/trade" className="text-foreground underline">
              Place an order →
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="mb-8 rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Created</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead>Side</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Trigger</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pending.map((order) => (
                <TableRow key={order.id}>
                  <TableCell className="text-muted-foreground">
                    {fmtDate(order.created_at)}
                  </TableCell>
                  <TableCell className="font-mono font-semibold">
                    <Link href={`/stocks/${order.ticker}`} className="hover:underline">
                      {order.ticker}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant={order.side === "buy" ? "default" : "secondary"}>
                      {order.side.toUpperCase()}
                    </Badge>
                  </TableCell>
                  <TableCell>{orderTypeLabel(order.order_type)}</TableCell>
                  <TableCell className="text-right font-mono">{fmtQty(order.quantity)}</TableCell>
                  <TableCell className="text-right font-mono">
                    {fmtCurrency(order.limit_price)}
                  </TableCell>
                  <TableCell className="text-right">
                    <form action={cancelOrderAction}>
                      <input type="hidden" name="id" value={order.id} />
                      <Button type="submit" variant="destructive" size="sm">
                        Cancel
                      </Button>
                    </form>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Order history */}
      {history.length > 0 && (
        <>
          <h2 className="mb-4 text-xl font-semibold">History</h2>
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="hidden sm:table-cell">Created</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="hidden text-right md:table-cell">Trigger</TableHead>
                  <TableHead className="text-right">Fill price</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">
                      {fmtDate(order.created_at)}
                    </TableCell>
                    <TableCell className="font-mono font-semibold">
                      <Link href={`/stocks/${order.ticker}`} className="hover:underline">
                        {order.ticker}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={order.side === "buy" ? "default" : "secondary"}>
                        {order.side.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell>{orderTypeLabel(order.order_type)}</TableCell>
                    <TableCell className="text-right font-mono">{fmtQty(order.quantity)}</TableCell>
                    <TableCell className="hidden text-right font-mono md:table-cell">
                      {fmtCurrency(order.limit_price)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {fmtCurrency(order.fill_price)}
                    </TableCell>
                    <TableCell>{statusBadge(order.status)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}
