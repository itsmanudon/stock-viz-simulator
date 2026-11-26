"use client";

/**
 * A4.6: the session's resting orders. Open ones can be cancelled; the others
 * say how they ended (filled, rejected with the reason, cancelled, expired).
 */

import { useActionState } from "react";

import {
  type ReplayActionState,
  cancelReplayOrderAction,
} from "@/app/(product)/(authed)/replay/actions";
import { ResearchSectionHeader } from "@/components/research-page-header";
import type { ReplayOrder } from "@/lib/api/replay";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { formatReplayShortDate, replayOrderTypeLabel } from "@/lib/replay";

const STATUS: Record<ReplayOrder["status"], string> = {
  open: "Open",
  filled: "Filled",
  cancelled: "Cancelled",
  rejected: "Rejected",
  expired: "Expired",
};

function CancelButton({ sessionId, orderId }: { sessionId: number; orderId: number }) {
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    cancelReplayOrderAction,
    {},
  );
  return (
    <form action={action} className="inline">
      <input type="hidden" name="session_id" value={sessionId} />
      <input type="hidden" name="order_id" value={orderId} />
      <button
        type="submit"
        disabled={pending}
        className="rounded-sm border border-border-muted px-2 py-0.5 text-xs text-text-secondary hover:text-foreground disabled:opacity-40"
        data-testid="replay-order-cancel"
      >
        {pending ? "Cancelling…" : "Cancel"}
      </button>
      {state.error ? (
        <span role="alert" className="ml-2 text-xs text-negative">
          {state.error}
        </span>
      ) : null}
    </form>
  );
}

export function ReplayOrders({
  sessionId,
  orders,
  currency,
  readOnly,
}: {
  sessionId: number;
  orders: ReplayOrder[];
  currency: string;
  readOnly: boolean;
}) {
  if (orders.length === 0) return null;
  const newest = [...orders].reverse();
  return (
    <section aria-labelledby="replay-orders-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-orders-heading"
        title="Resting orders"
        description="Limit and stop orders, checked against each later close as you step."
      />
      <ul
        className="divide-y divide-border-muted border-y border-border-muted text-sm sm:border-x"
        data-testid="replay-orders"
      >
        {newest.map((order) => (
          <li
            key={order.id}
            className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
            data-testid="replay-order"
            data-status={order.status}
          >
            <div className="min-w-0">
              <p className="font-medium">
                {replayOrderTypeLabel(order.order_type)} {order.side}{" "}
                {formatQuantity(order.quantity)} {order.ticker} at{" "}
                <span className="font-mono tabular-nums">
                  {formatCurrency(order.limit_price, currency)}
                </span>
              </p>
              <p className="text-xs text-text-tertiary">
                Placed {formatReplayShortDate(order.placed_at)}
                {order.resolved_at
                  ? ` · ${STATUS[order.status].toLowerCase()} ${formatReplayShortDate(order.resolved_at)}`
                  : ""}
                {order.reason && order.status !== "open" ? ` · ${order.reason}` : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-secondary">{STATUS[order.status]}</span>
              {order.status === "open" && !readOnly ? (
                <CancelButton sessionId={sessionId} orderId={order.id} />
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
