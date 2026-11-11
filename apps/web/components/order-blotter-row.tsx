import Link from "next/link";

import { cancelOrderAction } from "@/app/(product)/(authed)/orders/actions";
import { CancelOrderButton } from "@/components/cancel-order-button";
import {
  OrderSideBadge,
  OrderStatusBadge,
  OrderTypeBadge,
} from "@/components/operational-page-header";
import { parseApiTimestamp } from "@/lib/api-time";
import type { PendingOrder } from "@/lib/api/trading";
import { buildTradeHref, formatNativePrice, userCancelReason } from "@/lib/operational-trading";
import { formatQuantity } from "@/lib/portfolio-view-model";

/** Order times are stored in UTC; show them in UTC and say so (audit T4). */
function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return parseApiTimestamp(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function settlementNote(order: PendingOrder): string {
  return order.status === "pending"
    ? "Waiting on the next stored daily close that meets the condition."
    : order.status === "filled"
      ? fmtWhen(order.filled_at)
      : userCancelReason(order.cancel_reason);
}

function OrderAction({ order }: { order: PendingOrder }) {
  return order.status === "pending" ? (
    <form action={cancelOrderAction}>
      <input type="hidden" name="id" value={order.id} />
      <input type="hidden" name="ticker" value={order.ticker} />
      <CancelOrderButton />
    </form>
  ) : (
    <Link href={buildTradeHref(order.ticker)} className="text-xs hover:underline">
      Trade
    </Link>
  );
}

export function OrderBlotterRow({
  order,
  currencies,
}: {
  order: PendingOrder;
  currencies: Record<string, string>;
}) {
  const native = (amount: string | null) => formatNativePrice(amount, order.ticker, currencies);
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
      <td className="px-3 py-3 text-right font-mono">{native(order.limit_price)}</td>
      <td className="px-3 py-3">
        <OrderStatusBadge status={order.status} />
      </td>
      <td className="hidden px-3 py-3 text-text-tertiary md:table-cell">
        {fmtWhen(order.created_at)}
      </td>
      <td className="hidden px-3 py-3 text-xs leading-5 text-text-secondary lg:table-cell">
        {settlementNote(order)}
      </td>
      <td className="px-3 py-3 text-right font-mono">
        {order.fill_price ? native(order.fill_price) : "—"}
      </td>
      <td className="px-3 py-3 text-right">
        <OrderAction order={order} />
      </td>
    </tr>
  );
}

/**
 * The same order as a card, for screens under `md` where the 52rem table
 * scrolled sideways (UI audit P1). Every figure in the row is here too.
 */
export function OrderCard({
  order,
  currencies,
}: {
  order: PendingOrder;
  currencies: Record<string, string>;
}) {
  const native = (amount: string | null) => formatNativePrice(amount, order.ticker, currencies);
  const facts: [string, string][] = [
    ["Quantity", formatQuantity(order.quantity)],
    ["Trigger", native(order.limit_price)],
    ["Fill", order.fill_price ? native(order.fill_price) : "—"],
    ["Created", fmtWhen(order.created_at)],
  ];
  return (
    <li className="grid gap-3 rounded-2xl border border-border-muted bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1.5">
          <Link
            href={`/stocks/${order.ticker}`}
            className="font-mono text-base font-medium hover:underline"
          >
            {order.ticker}
          </Link>
          <span className="flex flex-wrap gap-1.5">
            <OrderSideBadge side={order.side} />
            <OrderTypeBadge type={order.order_type} />
          </span>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt className="text-text-tertiary">{label}</dt>
            <dd className="mt-0.5 font-mono" data-financial>
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs leading-5 text-text-secondary">{settlementNote(order)}</p>
      <div className="flex justify-end border-t border-border-muted pt-3">
        <OrderAction order={order} />
      </div>
    </li>
  );
}

export function PendingOrderQuote({
  order,
  currencies,
}: {
  order: PendingOrder;
  currencies: Record<string, string>;
}) {
  return (
    <>
      {formatQuantity(order.quantity)} @{" "}
      {formatNativePrice(order.limit_price, order.ticker, currencies)}
    </>
  );
}
