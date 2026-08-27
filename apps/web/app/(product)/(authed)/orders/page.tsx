/**
 * /orders — operational blotter for limit / stop-loss / take-profit orders.
 *
 * URL: ?status=pending|filled|cancelled|all (default pending).
 * Market fills live on /trades; this page is conditional paper orders.
 */

import Link from "next/link";

import { CancelOrderButton } from "@/components/cancel-order-button";
import {
  OperationalEmptyState,
  OperationalPageHeader,
  OperationalSubnav,
  OrderSideBadge,
  OrderStatusBadge,
  OrderTypeBadge,
} from "@/components/operational-page-header";
import { PageFrame } from "@/components/page-frame";
import { type PendingOrder, listOrders } from "@/lib/api/trading";
import {
  type OrderStatusFilter,
  buildOrdersHref,
  buildTradeHref,
  parseOrdersStatus,
  userCancelReason,
} from "@/lib/operational-trading";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";
import { cancelOrderAction } from "./actions";

const FILTERS: { value: OrderStatusFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "filled", label: "Filled" },
  { value: "cancelled", label: "Cancelled" },
  { value: "all", label: "All" },
];

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function emptyCopy(status: OrderStatusFilter): { title: string; body: string } {
  switch (status) {
    case "pending":
      return {
        title: "No pending orders",
        body: "Limit, stop-loss, and take-profit conditions appear here until the weekday close job fills or cancels them.",
      };
    case "filled":
      return {
        title: "No filled orders",
        body: "When a pending condition meets a stored daily close, the fill price and time show here.",
      };
    case "cancelled":
      return {
        title: "No cancelled orders",
        body: "User cancels and settlement failures (insufficient cash or shares) land in this list with a reason when the API provides one.",
      };
    default:
      return {
        title: "No orders yet",
        body: "Submit a limit, stop-loss, or take-profit order from the trade ticket or a stock workspace.",
      };
  }
}

export default async function OrdersPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status: rawStatus } = await searchParams;
  const status = parseOrdersStatus(rawStatus);
  const orders = status === "all" ? await listOrders() : await listOrders(status);

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <OperationalPageHeader
        eyebrow="Trade"
        title="Orders"
        description="Manage conditional paper orders. Pending buys reserve cash; pending sells reserve shares. Settlement uses the stored daily close, not an intraday trigger."
        actions={
          <Link href="/trade" className="text-sm hover:underline">
            Open trade ticket
          </Link>
        }
      />
      <OperationalSubnav current="/orders" />

      <nav
        aria-label="Order status"
        className="mt-6 flex flex-wrap gap-1 border-b border-border-muted"
      >
        {FILTERS.map((filter) => {
          const active = filter.value === status;
          return (
            <Link
              key={filter.value}
              href={buildOrdersHref(filter.value)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-10 items-center border-b-2 px-3 text-sm",
                active
                  ? "border-brand font-medium text-foreground"
                  : "border-transparent text-text-tertiary hover:text-foreground",
              )}
            >
              {filter.label}
            </Link>
          );
        })}
      </nav>

      {orders.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState
            title={emptyCopy(status).title}
            action={
              <Link href="/trade" className="text-sm hover:underline">
                Place an order
              </Link>
            }
          >
            <p>{emptyCopy(status).body}</p>
          </OperationalEmptyState>
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto border-y border-border-muted">
          <table className="w-full min-w-[52rem] text-sm">
            <caption className="sr-only">
              {status === "all" ? "All paper orders" : `${status} paper orders`}
            </caption>
            <thead>
              <tr className="border-b border-border-muted text-left text-[10px] font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                <th scope="col" className="px-3 py-2.5">
                  Ticker
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Side
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Type
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Qty
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Trigger
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Status
                </th>
                <th scope="col" className="hidden px-3 py-2.5 md:table-cell">
                  Created
                </th>
                <th scope="col" className="hidden px-3 py-2.5 lg:table-cell">
                  Filled / cancelled
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Fill
                </th>
                <th scope="col" className="px-3 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <OrderRow key={order.id} order={order} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageFrame>
  );
}

function OrderRow({ order }: { order: PendingOrder }) {
  const settledAt = order.filled_at;
  return (
    <tr className="border-b border-border-muted last:border-0 align-top">
      <td className="px-3 py-3 font-mono">
        <Link href={`/stocks/${order.ticker}`} className="hover:underline">
          {order.ticker}
        </Link>
      </td>
      <td className="px-3 py-3">
        <OrderSideBadge side={order.side} />
      </td>
      <td className="px-3 py-3">
        <OrderTypeBadge type={order.order_type} />
      </td>
      <td className="px-3 py-3 text-right font-mono">{formatQuantity(order.quantity)}</td>
      <td className="px-3 py-3 text-right font-mono">{formatCurrency(order.limit_price, "USD")}</td>
      <td className="px-3 py-3">
        <OrderStatusBadge status={order.status} />
      </td>
      <td className="hidden px-3 py-3 text-text-tertiary md:table-cell">
        {fmtWhen(order.created_at)}
      </td>
      <td className="hidden px-3 py-3 text-xs leading-5 text-text-secondary lg:table-cell">
        {order.status === "pending"
          ? "Waiting on the next stored daily close that meets the condition."
          : order.status === "filled"
            ? fmtWhen(settledAt)
            : userCancelReason(order.cancel_reason)}
      </td>
      <td className="px-3 py-3 text-right font-mono">
        {order.fill_price ? formatCurrency(order.fill_price, "USD") : "—"}
      </td>
      <td className="px-3 py-3 text-right">
        {order.status === "pending" ? (
          <form action={cancelOrderAction}>
            <input type="hidden" name="id" value={order.id} />
            <input type="hidden" name="ticker" value={order.ticker} />
            <CancelOrderButton />
          </form>
        ) : (
          <Link href={buildTradeHref(order.ticker)} className="text-xs hover:underline">
            Trade
          </Link>
        )}
      </td>
    </tr>
  );
}
