/**
 * /orders — operational blotter for limit / stop-loss / take-profit orders.
 *
 * URL: ?status=pending|filled|cancelled|all (default pending).
 * Market fills are recorded on /trades; this page is conditional paper orders.
 */

import Link from "next/link";

import {
  OperationalEmptyState,
  OperationalPageHeader,
  OperationalSubnav,
} from "@/components/operational-page-header";
import { OrderBlotterRow } from "@/components/order-blotter-row";
import { PageFrame } from "@/components/page-frame";
import { listSymbols } from "@/lib/api";
import { listOrders } from "@/lib/api/trading";
import {
  type OrderStatusFilter,
  buildOrdersHref,
  currencyByTicker,
  parseOrdersStatus,
} from "@/lib/operational-trading";
import { cn } from "@/lib/utils";

const FILTERS: { value: OrderStatusFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "filled", label: "Filled" },
  { value: "cancelled", label: "Cancelled" },
  { value: "all", label: "All" },
];

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
  const [orders, symbols] = await Promise.all([
    status === "all" ? listOrders() : listOrders(status),
    listSymbols().catch(() => []),
  ]);
  const currencies = currencyByTicker(symbols);

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
              <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
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
                <OrderBlotterRow key={order.id} order={order} currencies={currencies} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageFrame>
  );
}
