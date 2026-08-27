import Link from "next/link";

import { cancelOrderAction } from "@/app/(product)/(authed)/orders/actions";
import { CancelOrderButton } from "@/components/cancel-order-button";
import {
  OrderSideBadge,
  OrderStatusBadge,
  OrderTypeBadge,
} from "@/components/operational-page-header";
import type { PendingOrder } from "@/lib/api/trading";
import { buildTradeHref, formatNativePrice, userCancelReason } from "@/lib/operational-trading";
import { formatQuantity } from "@/lib/portfolio-view-model";

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

export function OrderBlotterRow({
  order,
  currencies,
}: {
  order: PendingOrder;
  currencies: Record<string, string>;
}) {
  const native = (amount: string | null) => formatNativePrice(amount, order.ticker, currencies);
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
      <td className="px-3 py-3 text-right font-mono">{native(order.limit_price)}</td>
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
        {order.fill_price ? native(order.fill_price) : "—"}
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
