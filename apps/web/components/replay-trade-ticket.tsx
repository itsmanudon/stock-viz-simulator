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
import { REPLAY_PROFILE_LABEL } from "@/lib/replay";
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
}: {
  sessionId: number;
  ticker: string;
  currentClose: string;
  cash: string;
  quantityHeld: string;
  readOnly: boolean;
  initialSide?: Side;
}) {
  const fieldId = useId();
  const [side, setSide] = useState<Side>(initialSide);
  const [quantity, setQuantity] = useState("1");
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    submitReplayOrderAction,
    {},
  );
  const close = Number(currentClose);
  const qty = Number(quantity);
  const notional = Number.isFinite(close) && Number.isFinite(qty) ? close * qty : null;

  return (
    <section aria-labelledby={`${fieldId}-title`} className="space-y-5">
      <div>
        <p className="text-[11px] font-semibold tracking-[0.14em] text-brand uppercase">
          Replay order
        </p>
        <h2 id={`${fieldId}-title`} className="mt-1 text-sm font-semibold">
          {ticker} market ticket
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          Fills at this session&apos;s stored daily close. Not live paper trading. Conditional
          orders are not held overnight.
        </p>
      </div>

      {readOnly ? (
        <p className="border-y border-border-muted py-4 text-sm text-text-secondary">
          This replay is read-only. Start another session to trade again.
        </p>
      ) : (
        <form action={action} className="space-y-4">
          <input type="hidden" name="session_id" value={sessionId} />
          <input type="hidden" name="side" value={side} />
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setSide("buy")}
              aria-pressed={side === "buy"}
              className={cn(
                "h-10 rounded-md border text-sm font-semibold",
                side === "buy"
                  ? "border-positive/40 bg-positive/10 text-positive"
                  : "border-border-muted text-text-secondary",
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide("sell")}
              aria-pressed={side === "sell"}
              className={cn(
                "h-10 rounded-md border text-sm font-semibold",
                side === "sell"
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
          <dl className="space-y-1.5 text-xs text-text-tertiary">
            <div className="flex justify-between gap-3">
              <dt>Current replay close</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {formatCurrency(currentClose)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Estimated notional</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {notional === null ? "—" : formatCurrency(notional)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Replay cash</dt>
              <dd className="font-mono tabular-nums text-foreground">{formatCurrency(cash)}</dd>
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
              Filled {state.side?.toUpperCase()} {state.quantity} {ticker} @{" "}
              {formatCurrency(state.fillPrice ?? "0")}
            </output>
          ) : null}
          <Button type="submit" disabled={pending || !(qty > 0)} className="w-full">
            {pending ? "Submitting…" : `Submit market ${side}`}
          </Button>
        </form>
      )}
    </section>
  );
}
