import { X } from "lucide-react";

import { cancelOrderAction } from "@/app/(product)/(authed)/orders/actions";
import { Button } from "@/components/ui/button";
import type { PendingOrder } from "@/lib/api/trading";
import { formatQuantity } from "@/lib/stock-workspace";

function money(value: string, currency: string): string {
  const number = Number(value);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(number);
  } catch {
    return `${currency} ${number.toFixed(2)}`;
  }
}

export function TickerOrders({
  ticker,
  currency,
  orders,
}: {
  ticker: string;
  currency: string;
  orders: PendingOrder[] | null;
}) {
  return (
    <section aria-labelledby="ticker-orders-title" className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="ticker-orders-title" className="text-base font-semibold">
          Open orders
        </h3>
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          {orders === null ? "Unavailable" : `${orders.length} pending`}
        </span>
      </div>
      {orders === null ? (
        <p className="border-y border-border-muted py-6 text-sm text-warning">
          Order data is temporarily unavailable.
        </p>
      ) : orders.length ? (
        <ul className="divide-y divide-border-muted border-y border-border-muted">
          {orders.map((order) => (
            <li key={order.id} className="flex flex-wrap items-center gap-3 py-3 sm:flex-nowrap">
              <span
                className={`w-24 shrink-0 font-mono text-xs font-semibold ${
                  order.side === "buy" ? "text-positive" : "text-negative"
                }`}
              >
                {order.side.toUpperCase()} {order.order_type.replace("_", " ").toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 font-mono text-sm tabular-nums">
                {formatQuantity(order.quantity)} {ticker} @ {money(order.limit_price, currency)}
              </span>
              <span className="rounded-sm bg-surface-secondary px-2 py-1 text-3xs font-semibold uppercase tracking-[0.1em] text-text-tertiary">
                Pending
              </span>
              <form action={cancelOrderAction}>
                <input type="hidden" name="id" value={order.id} />
                <input type="hidden" name="ticker" value={ticker} />
                <Button
                  type="submit"
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Cancel ${ticker} ${order.side} ${order.order_type.replace("_", " ")} order`}
                >
                  <X aria-hidden />
                </Button>
              </form>
            </li>
          ))}
        </ul>
      ) : (
        <p className="border-y border-border-muted py-6 text-sm text-muted-foreground">
          No pending orders for {ticker}.
        </p>
      )}
    </section>
  );
}
