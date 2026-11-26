"use client";

/**
 * A4.6: the session's resting orders. Open ones can be cancelled; the others
 * say how they ended (filled, rejected with the reason, cancelled, expired).
 * A6.9: a bracket shows as one linked group: its entry, then its stop and
 * target (pending until the entry fills; one cancels the other). A stop that
 * filled first with the order inside its bar unknown carries a badge.
 */

import { useActionState } from "react";

import {
  type ReplayActionState,
  cancelReplayOrderAction,
} from "@/app/(product)/(authed)/replay/actions";
import { ResearchSectionHeader } from "@/components/research-page-header";
import type { ReplayOrder } from "@/lib/api/replay";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { formatReplayShortDate, groupReplayOrders, replayOrderTypeLabel } from "@/lib/replay";

const STATUS: Record<ReplayOrder["status"], string> = {
  pending: "Waiting for entry",
  open: "Open",
  filled: "Filled",
  cancelled: "Cancelled",
  rejected: "Rejected",
  expired: "Expired",
};

function CancelButton({
  sessionId,
  orderId,
  target,
}: {
  sessionId: number;
  orderId: number;
  target: "replay" | "drill";
}) {
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    cancelReplayOrderAction,
    {},
  );
  return (
    <form action={action} className="inline">
      <input type="hidden" name="session_id" value={sessionId} />
      <input type="hidden" name="order_id" value={orderId} />
      <input type="hidden" name="target" value={target} />
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

/** The label a stop carries when it filled first with the order inside the bar unknown. */
export const ORDER_UNKNOWN_BADGE = "Order Inside the Bar Unknown";

function OrderLine({
  order,
  currency,
}: {
  order: ReplayOrder;
  currency: string;
}) {
  return (
    <p className="text-xs text-text-tertiary">
      Placed {formatReplayShortDate(order.placed_at)}
      {order.resolved_at
        ? ` · ${STATUS[order.status].toLowerCase()} ${formatReplayShortDate(order.resolved_at)}`
        : ""}
      {order.reason && order.status !== "open" && order.status !== "pending"
        ? ` · ${order.reason}`
        : ""}
      <span className="sr-only"> ({formatCurrency(order.limit_price, currency)})</span>
    </p>
  );
}

function UnknownBadge({ order }: { order: ReplayOrder }) {
  if (!order.order_inside_bar_unknown) return null;
  return (
    <span
      className="inline-flex items-center rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-2xs font-medium text-warning"
      data-testid="replay-order-unknown"
      title="The stop and the target were both inside one bar and no stored minutes said which came first, so the stop filled (worst case)."
    >
      {ORDER_UNKNOWN_BADGE}
    </span>
  );
}

function Actions({
  order,
  sessionId,
  readOnly,
  target,
}: {
  order: ReplayOrder;
  sessionId: number;
  readOnly: boolean;
  target: "replay" | "drill";
}) {
  return (
    <div className="flex items-center gap-2">
      <UnknownBadge order={order} />
      <span className="text-xs text-text-secondary">{STATUS[order.status]}</span>
      {(order.status === "open" || order.status === "pending") && !readOnly ? (
        <CancelButton sessionId={sessionId} orderId={order.id} target={target} />
      ) : null}
    </div>
  );
}

function BracketLeg({
  label,
  order,
  currency,
  sessionId,
  readOnly,
  target,
}: {
  label: string;
  order: ReplayOrder | null;
  currency: string;
  sessionId: number;
  readOnly: boolean;
  target: "replay" | "drill";
}) {
  if (!order) return null;
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-2 border-l-2 border-border-muted py-2 pl-3"
      data-testid="replay-bracket-leg"
      data-leg={order.order_type}
      data-status={order.status}
    >
      <div className="min-w-0">
        <p className="text-sm">
          {label} sell {formatQuantity(order.quantity)} at{" "}
          <span className="font-mono tabular-nums">
            {formatCurrency(order.limit_price, currency)}
          </span>
        </p>
        <OrderLine order={order} currency={currency} />
      </div>
      <Actions order={order} sessionId={sessionId} readOnly={readOnly} target={target} />
    </li>
  );
}

export function ReplayOrders({
  sessionId,
  orders,
  currency,
  readOnly,
  target = "replay",
  profileName = "legacy_close",
}: {
  sessionId: number;
  orders: ReplayOrder[];
  currency: string;
  readOnly: boolean;
  target?: "replay" | "drill";
  /** A6.9: the session's profile, which says how resting orders are judged. */
  profileName?: string;
}) {
  if (orders.length === 0) return null;
  const rows = groupReplayOrders(orders);
  const judged =
    profileName === "intrabar_ohlc"
      ? "judged on each later bar's range, the open first"
      : "checked against each later close";
  return (
    <section aria-labelledby="replay-orders-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-orders-heading"
        title="Resting orders"
        description={`Limit and stop orders and brackets, ${judged} as you step.`}
      />
      <ul
        className="divide-y divide-border-muted border-y border-border-muted text-sm sm:border-x"
        data-testid="replay-orders"
      >
        {rows.map((row) =>
          row.kind === "single" ? (
            <li
              key={row.order.id}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
              data-testid="replay-order"
              data-status={row.order.status}
            >
              <div className="min-w-0">
                <p className="font-medium">
                  {replayOrderTypeLabel(row.order.order_type)} {row.order.side}{" "}
                  {formatQuantity(row.order.quantity)} {row.order.ticker} at{" "}
                  <span className="font-mono tabular-nums">
                    {formatCurrency(row.order.limit_price, currency)}
                  </span>
                </p>
                <OrderLine order={row.order} currency={currency} />
              </div>
              <Actions
                order={row.order}
                sessionId={sessionId}
                readOnly={readOnly}
                target={target}
              />
            </li>
          ) : (
            <li
              key={row.entry.id}
              className="space-y-2 px-4 py-3"
              data-testid="replay-bracket"
              data-oco-group={row.entry.oco_group ?? row.entry.id}
              data-status={row.entry.status}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium">
                    Bracket buy {formatQuantity(row.entry.quantity)} {row.entry.ticker}:{" "}
                    {row.entry.status === "filled" ? "entry filled at " : "limit entry at "}
                    <span className="font-mono tabular-nums">
                      {formatCurrency(row.entry.limit_price, currency)}
                    </span>
                  </p>
                  <OrderLine order={row.entry} currency={currency} />
                </div>
                <Actions
                  order={row.entry}
                  sessionId={sessionId}
                  readOnly={readOnly}
                  target={target}
                />
              </div>
              <ul aria-label="Stop and target, one cancels the other" className="space-y-1">
                <BracketLeg
                  label="Stop"
                  order={row.stop}
                  currency={currency}
                  sessionId={sessionId}
                  readOnly={readOnly}
                  target={target}
                />
                <BracketLeg
                  label="Target"
                  order={row.target}
                  currency={currency}
                  sessionId={sessionId}
                  readOnly={readOnly}
                  target={target}
                />
              </ul>
              <p className="text-2xs text-text-tertiary">
                {row.stop?.status === "pending"
                  ? "The stop and the target wait for the entry to fill."
                  : "One cancels the other: when one fills, the other is cancelled."}
              </p>
            </li>
          ),
        )}
      </ul>
    </section>
  );
}
