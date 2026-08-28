import Link from "next/link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import type { PendingOrder } from "@/lib/api/trading";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";

const ORDER_TYPE_LABELS: Record<PendingOrder["order_type"], string> = {
  limit: "Limit",
  stop_loss: "Stop",
  take_profit: "Target",
};

/** Working orders that haven't filled yet — the "what's still open" glance. */
export function OrdersWidget({
  orders,
  displayCurrency,
}: {
  orders: PendingOrder[] | null;
  displayCurrency: string;
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
                  <span
                    className={cn(
                      "font-mono text-xs font-semibold uppercase",
                      order.side === "buy" ? "text-positive" : "text-negative",
                    )}
                  >
                    {order.side}
                  </span>
                  <span className="font-mono text-sm font-semibold">{order.ticker}</span>
                </span>
                <span className="mt-0.5 block text-xs text-text-tertiary">
                  {ORDER_TYPE_LABELS[order.order_type]} · {formatQuantity(order.quantity)} sh
                </span>
              </span>
              <span className="shrink-0 font-mono text-sm" data-financial>
                {formatCurrency(order.limit_price, displayCurrency)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}
