"use client";

import { useActionState, useId, useState } from "react";

import {
  type ReplayActionState,
  submitReplayOrderAction,
} from "@/app/(product)/(authed)/replay/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import {
  REPLAY_ORDER_TYPES,
  REPLAY_PROFILE_LABEL,
  type ReplayTicketOrderType,
  replayOrderTypeLabel,
} from "@/lib/replay";
import { cn } from "@/lib/utils";

type Side = "buy" | "sell";

export function ReplayTradeTicket({
  sessionId,
  ticker,
  currentClose,
  cash,
  quantityHeld,
  readOnly,
  initialSide = "buy",
  currency = "USD",
  tradable = true,
  feeSchedule = "none",
}: {
  sessionId: number;
  ticker: string;
  currentClose: string;
  cash: string;
  quantityHeld: string;
  readOnly: boolean;
  initialSide?: Side;
  /** A4.6: the session's currency; every amount here is in it. */
  currency?: string;
  /** False for an index session (watch only). */
  tradable?: boolean;
  feeSchedule?: string;
}) {
  const fieldId = useId();
  const [side, setSide] = useState<Side>(initialSide);
  const [quantity, setQuantity] = useState("1");
  const [orderType, setOrderType] = useState<ReplayTicketOrderType>("market");
  const [price, setPrice] = useState(() => {
    const value = Number(currentClose);
    return Number.isFinite(value) ? String(value) : currentClose;
  });
  const resting = orderType !== "market";
  const sellOnly = orderType === "stop_loss" || orderType === "take_profit";
  const effectiveSide: Side = sellOnly ? "sell" : side;
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    submitReplayOrderAction,
    {},
  );
  const close = Number(resting ? price : currentClose);
  const qty = Number(quantity);
  const notional = Number.isFinite(close) && Number.isFinite(qty) ? close * qty : null;
  const money = (value: string | number) => formatCurrency(value, currency);

  return (
    <section aria-labelledby={`${fieldId}-title`} className="space-y-5">
      <div>
        <p className="text-[11px] font-semibold tracking-[0.14em] text-brand uppercase">
          Replay order
        </p>
        <h2 id={`${fieldId}-title`} className="mt-1 text-sm font-semibold">
          {ticker} replay ticket
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          A market order fills at this session&apos;s stored daily close. A limit or stop order
          rests and is checked against each later close as you step. Not live paper trading.
          {feeSchedule !== "none" ? " Fills pay the exchange's dated delivery charges." : ""}
        </p>
      </div>

      {!tradable ? (
        <p
          className="border-y border-border-muted py-4 text-sm text-text-secondary"
          data-testid="replay-not-tradable"
        >
          {ticker} is an index: you can replay its chart, draw and add studies, but not trade it.
        </p>
      ) : readOnly ? (
        <p className="border-y border-border-muted py-4 text-sm text-text-secondary">
          This replay is read-only. Start another session to trade again.
        </p>
      ) : (
        <form action={action} className="space-y-4">
          <input type="hidden" name="session_id" value={sessionId} />
          <input type="hidden" name="side" value={effectiveSide} />
          <input type="hidden" name="order_type" value={orderType} />
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-type`}>Order type</Label>
            <select
              id={`${fieldId}-type`}
              value={orderType}
              onChange={(event) => setOrderType(event.target.value as ReplayTicketOrderType)}
              className="h-9 w-full rounded-md border border-border-muted bg-background px-2 text-sm"
              data-testid="replay-order-type"
            >
              {REPLAY_ORDER_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setSide("buy")}
              aria-pressed={effectiveSide === "buy"}
              disabled={sellOnly}
              className={cn(
                "h-10 rounded-md border text-sm font-semibold disabled:opacity-40",
                effectiveSide === "buy"
                  ? "border-positive/40 bg-positive/10 text-positive"
                  : "border-border-muted text-text-secondary",
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide("sell")}
              aria-pressed={effectiveSide === "sell"}
              className={cn(
                "h-10 rounded-md border text-sm font-semibold",
                effectiveSide === "sell"
                  ? "border-negative/40 bg-negative/10 text-negative"
                  : "border-border-muted text-text-secondary",
              )}
            >
              Sell
            </button>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-qty`}>Quantity</Label>
            <Input
              id={`${fieldId}-qty`}
              name="quantity"
              type="number"
              min="0.000001"
              step="0.000001"
              required
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
          </div>
          {resting ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-price`}>
                {orderType === "limit" ? "Limit price" : "Trigger price"} ({currency})
              </Label>
              <Input
                id={`${fieldId}-price`}
                name="limit_price"
                type="number"
                min="0"
                step="any"
                required
                value={price}
                onChange={(event) => setPrice(event.target.value)}
                data-testid="replay-limit-price"
              />
              <p className="text-2xs text-text-tertiary">
                {orderType === "limit"
                  ? effectiveSide === "buy"
                    ? "Fills at a later close at or below this price."
                    : "Fills at a later close at or above this price."
                  : orderType === "stop_loss"
                    ? "Sells at a later close at or below this price."
                    : "Sells at a later close at or above this price."}{" "}
                Checked from the next bar on; nothing is reserved.
              </p>
            </div>
          ) : null}
          <dl className="space-y-1.5 text-xs text-text-tertiary">
            <div className="flex justify-between gap-3">
              <dt>Current replay close</dt>
              <dd className="font-mono tabular-nums text-foreground">{money(currentClose)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>{resting ? "Notional at that price" : "Estimated notional"}</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {notional === null ? "—" : money(notional)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Replay cash</dt>
              <dd className="font-mono tabular-nums text-foreground">{money(cash)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Held</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {formatQuantity(quantityHeld)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Execution</dt>
              <dd>Current stored daily close · {REPLAY_PROFILE_LABEL}</dd>
            </div>
          </dl>
          {state.error ? (
            <p role="alert" className="text-sm text-negative">
              {state.error}
            </p>
          ) : null}
          {state.filled ? (
            <output className="block text-sm text-positive">
              Filled {state.side?.toUpperCase()} {formatQuantity(state.quantity ?? "0")} {ticker} @{" "}
              {money(state.fillPrice ?? "0")}
            </output>
          ) : null}
          {state.placed ? (
            <output className="block text-sm text-foreground" data-testid="replay-order-placed">
              Placed {replayOrderTypeLabel(state.orderType ?? "").toLowerCase()} {state.side}{" "}
              {formatQuantity(state.quantity ?? "0")} {ticker} at {money(state.limitPrice ?? "0")}.
              It is checked from the next bar.
            </output>
          ) : null}
          <Button
            type="submit"
            disabled={pending || !(qty > 0) || (resting && !(Number(price) > 0))}
            className="w-full"
          >
            {pending
              ? "Submitting…"
              : resting
                ? `Place ${replayOrderTypeLabel(orderType).toLowerCase()} ${effectiveSide}`
                : `Submit market ${effectiveSide}`}
          </Button>
        </form>
      )}
    </section>
  );
}
