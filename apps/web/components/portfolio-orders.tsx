import Link from "next/link";

import { cancelOrderAction } from "@/app/(product)/(authed)/orders/actions";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PendingOrder } from "@/lib/api/trading";
import { formatQuantity } from "@/lib/portfolio-view-model";

export function PortfolioOrders({ orders }: { orders: PendingOrder[] | null }) {
  if (orders === null) {
    return <PanelState>Order data is temporarily unavailable.</PanelState>;
  }

  if (orders.length === 0) {
    return (
      <PanelState>
        No pending orders across your portfolio. Orders placed from a stock workspace will appear
        here.
      </PanelState>
    );
  }

  return (
    <section aria-labelledby="portfolio-orders-heading">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="portfolio-orders-heading" className="text-lg font-semibold tracking-tight">
            Pending orders
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Reserved cash and shares remain unavailable until these orders fill or cancel.
          </p>
        </div>
        <Link href="/orders" className="text-xs font-medium text-brand hover:underline">
          View all orders
        </Link>
      </div>

      <div className="hidden overflow-hidden border-y border-border-muted md:block">
        <Table aria-label="Pending portfolio orders">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right">Quantity</TableHead>
              <TableHead className="text-right">Native quote</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {orders.map((order) => (
              <TableRow key={order.id} className="border-border-muted">
                <TableCell>
                  <Link
                    href={`/stocks/${order.ticker}`}
                    className="font-mono font-semibold hover:text-brand focus-visible:text-brand focus-visible:underline"
                  >
                    {order.ticker}
                  </Link>
                </TableCell>
                <TableCell>
                  <SideLabel side={order.side} />
                </TableCell>
                <TableCell>{orderTypeLabel(order.order_type)}</TableCell>
                <TableCell className="text-right font-mono" data-financial>
                  {formatQuantity(order.quantity)}
                </TableCell>
                <TableCell className="text-right font-mono" data-financial>
                  {formatNativeQuote(order.limit_price)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatTimestamp(order.created_at)}
                </TableCell>
                <TableCell className="text-xs font-medium text-muted-foreground">Pending</TableCell>
                <TableCell className="text-right">
                  <CancelOrderButton order={order} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul aria-label="Pending portfolio orders on mobile" className="divide-y divide-border-muted md:hidden">
        {orders.map((order) => (
          <li
            key={order.id}
            aria-label={`${order.ticker} ${order.side} ${orderTypeLabel(order.order_type)} order`}
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-5"
          >
            <div>
              <Link href={`/stocks/${order.ticker}`} className="font-mono font-semibold">
                {order.ticker}
              </Link>
              <div className="mt-1 flex items-center gap-2 text-xs">
                <SideLabel side={order.side} />
                <span>{orderTypeLabel(order.order_type)}</span>
                <span className="text-muted-foreground">Pending</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {formatQuantity(order.quantity)} shares · Native quote{" "}
                <span className="font-mono">{formatNativeQuote(order.limit_price)}</span>
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">{formatTimestamp(order.created_at)}</p>
              <div className="mt-3">
                <CancelOrderButton order={order} />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SideLabel({ side }: { side: PendingOrder["side"] }) {
  return (
    <span
      className={`inline-flex rounded-sm px-1.5 py-0.5 text-[11px] font-semibold ${
        side === "buy"
          ? "bg-positive/10 text-positive"
          : "bg-negative/10 text-negative"
      }`}
    >
      {side.toUpperCase()}
    </span>
  );
}

function CancelOrderButton({ order }: { order: PendingOrder }) {
  return (
    <form action={cancelOrderAction}>
      <input type="hidden" name="id" value={order.id} />
      <input type="hidden" name="ticker" value={order.ticker} />
      <button
        type="submit"
        aria-label={`Cancel ${order.ticker} ${order.side} ${order.order_type.replaceAll("_", " ")} order`}
        className="rounded-md border border-negative/30 px-2.5 py-1 text-xs font-medium text-negative outline-none transition-colors hover:bg-negative/10 focus-visible:ring-2 focus-visible:ring-ring"
      >
        Cancel
      </button>
    </form>
  );
}

function PanelState({ children }: { children: string }) {
  return <p className="border-y border-border-muted py-8 text-sm text-muted-foreground">{children}</p>;
}

function orderTypeLabel(value: PendingOrder["order_type"]): string {
  return value
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function formatNativeQuote(raw: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

function formatTimestamp(raw: string): string {
  return new Date(raw).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
