import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { PendingOrder } from "@/lib/api/trading";
import { formatNativePrice } from "@/lib/operational-trading";
import { formatQuantity } from "@/lib/portfolio-view-model";

const ORDER_TYPE_LABELS: Record<PendingOrder["order_type"], string> = {
  limit: "Limit",
  stop_loss: "Stop",
  take_profit: "Target",
};

/**
 * Working orders that haven't filled yet — the "what's still open" glance.
 *
 * A trigger is an operational price, so it shows in the symbol's own
 * currency (an NSE limit in rupees), not the account's display currency.
 * `currencies` maps ticker to currency from what the dashboard already
 * loads (positions and watchlist); an unknown ticker falls back to USD, as
 * on /orders.
 */
export function OrdersWidget({
  orders,
  currencies = {},
}: {
  orders: PendingOrder[] | null;
  currencies?: Record<string, string>;
}) {
  const pending = orders ?? [];

  return (
    <WidgetCard
      title="Pending orders"
      titleId="dashboard-orders-heading"
      action={pending.length > 0 ? { label: "All orders", href: "/orders" } : undefined}
    >
      {orders === null ? (
        <WidgetEmpty>Orders are unavailable right now.</WidgetEmpty>
      ) : pending.length === 0 ? (
        <WidgetEmpty>
          No working orders.{" "}
          <Link href="/trade" className="font-medium text-brand hover:underline">
            Place one
          </Link>
          .
        </WidgetEmpty>
      ) : (
        <ul className="-my-2 divide-y divide-border-muted">
          {pending.slice(0, 4).map((order) => (
            <li key={order.id} className="flex items-center justify-between gap-3 py-2.5">
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  {/* Neutral: the side of an order is not a gain or a loss. */}
                  <span className="inline-flex items-center gap-1 font-mono text-xs font-semibold text-text-secondary uppercase">
                    <span aria-hidden>{order.side === "buy" ? "↗" : "↘"}</span>
                    <span>{order.side}</span>
                  </span>
                  <span className="font-mono text-sm font-semibold">{order.ticker}</span>
                </span>
                <span className="mt-0.5 block text-xs text-text-tertiary">
                  {ORDER_TYPE_LABELS[order.order_type]} · {formatQuantity(order.quantity)} sh
                </span>
              </span>
              <span className="shrink-0 font-mono text-sm" data-financial>
                {formatNativePrice(order.limit_price, order.ticker, currencies)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {pending.length > 0 ? (
        <p className="mt-auto border-t border-border-muted pt-3 text-2xs text-text-tertiary">
          Checked after each weekday close, and filled at that close.
        </p>
      ) : null}
    </WidgetCard>
  );
}
