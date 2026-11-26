"use client";

import { useActionState, useId, useState } from "react";

import {
  type ReplayActionState,
  submitReplayOrderAction,
} from "@/app/(product)/(authed)/replay/actions";
import { useOutcomeSound } from "@/components/sound/sound-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import {
  REPLAY_ORDER_TYPES,
  type ReplayTicketOrderType,
  replayOrderTypeLabel,
  replayProfileLabel,
} from "@/lib/replay";
import { titleCase } from "@/lib/title-case";
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
  target = "replay",
  profileName = "legacy_close",
  profileVersion = "v1",
}: {
  /** The replay session's id, or the drill's when `target` is "drill". */
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
  /** A4.7: orders for a drill go through `/v1/drills/{id}/orders`. */
  target?: "replay" | "drill";
  /** A6.9: the session's profile (`legacy_close` or `intrabar_ohlc`). */
  profileName?: string;
  profileVersion?: string;
}) {
  const fieldId = useId();
  const [side, setSide] = useState<Side>(initialSide);
  const [quantity, setQuantity] = useState("1");
  const [orderType, setOrderType] = useState<ReplayTicketOrderType>("market");
  const [price, setPrice] = useState(() => {
    const value = Number(currentClose);
    return Number.isFinite(value) ? String(value) : currentClose;
  });
  const [entryType, setEntryType] = useState<"market" | "limit">("market");
  const [stop, setStop] = useState(() => defaultLevel(currentClose, 0.95));
  const [targetPrice, setTargetPrice] = useState(() => defaultLevel(currentClose, 1.05));
  const bracket = orderType === "bracket";
  const intrabar = profileName === "intrabar_ohlc";
  const resting = orderType !== "market" && !(bracket && entryType === "market");
  const sellOnly = orderType === "stop_loss" || orderType === "take_profit";
  // Owner, 27 Nov 2026: a bracket can sell short, on US listings only (the
  // API refuses NSE/BSE sessions the same way).
  const shortable = currency === "USD";
  const effectiveSide: Side = sellOnly ? "sell" : bracket && !shortable ? "buy" : side;
  const shortBracket = bracket && effectiveSide === "sell";
  const checked = intrabar ? "each later bar's range, the open first" : "each later close";
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    submitReplayOrderAction,
    {},
  );
  useOutcomeSound(state.status, state.error, "fill");
  const close = Number(resting ? price : currentClose);
  const bracketProblem = bracket
    ? bracketLevelsProblem(
        resting ? price : currentClose,
        stop,
        targetPrice,
        shortBracket ? "short" : "long",
      )
    : null;
  const qty = Number(quantity);
  const notional = Number.isFinite(close) && Number.isFinite(qty) ? close * qty : null;
  const money = (value: string | number) => formatCurrency(value, currency);

  return (
    <section aria-labelledby={`${fieldId}-title`} className="space-y-5">
      <div>
        <p className="text-[11px] font-semibold tracking-[0.02em] text-brand">
          {target === "drill" ? "Drill Order" : "Replay Order"}
        </p>
        <h2 id={`${fieldId}-title`} className="mt-1 text-sm font-semibold">
          {ticker} replay ticket
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          A market order fills at this session&apos;s stored close. A limit or stop order rests and
          is checked against {checked} as you step. A bracket buys with a stop and a target that
          cancel each other. Not live paper trading.
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
          {target === "drill"
            ? "This drill is finished: reveal it to see what happened."
            : "This replay is read-only. Start another session to trade again."}
        </p>
      ) : (
        <form action={action} className="space-y-4">
          <input type="hidden" name="session_id" value={sessionId} />
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="side" value={effectiveSide} />
          <input type="hidden" name="order_type" value={orderType} />
          {bracket ? <input type="hidden" name="entry_type" value={entryType} /> : null}
          {bracket ? (
            <input type="hidden" name="direction" value={shortBracket ? "short" : "long"} />
          ) : null}
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
              onClick={() => {
                if (bracket && side === "sell") {
                  setStop(defaultLevel(currentClose, 0.95));
                  setTargetPrice(defaultLevel(currentClose, 1.05));
                }
                setSide("buy");
              }}
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
              onClick={() => {
                if (bracket && side !== "sell") {
                  // A short bracket's stop is above the entry and its target below.
                  setStop(defaultLevel(currentClose, 1.05));
                  setTargetPrice(defaultLevel(currentClose, 0.95));
                }
                setSide("sell");
              }}
              aria-pressed={effectiveSide === "sell"}
              disabled={bracket && !shortable}
              title={bracket && !shortable ? "Short brackets are for US listings only" : undefined}
              className={cn(
                "h-10 rounded-md border text-sm font-semibold disabled:opacity-40",
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
          {bracket ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-entry`}>Entry</Label>
              <select
                id={`${fieldId}-entry`}
                value={entryType}
                onChange={(event) => setEntryType(event.target.value as "market" | "limit")}
                className="h-9 w-full rounded-md border border-border-muted bg-background px-2 text-sm"
                data-testid="replay-bracket-entry"
              >
                <option value="market">Market, at this close</option>
                <option value="limit">Limit, resting</option>
              </select>
            </div>
          ) : null}
          {resting ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-price`}>
                {orderType === "limit" || bracket ? "Limit price" : "Trigger price"} ({currency})
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
                {restingHelp(
                  orderType === "bracket" ? "limit" : orderType,
                  effectiveSide,
                  intrabar,
                )}{" "}
                Checked from the next bar on; nothing is reserved.
              </p>
            </div>
          ) : null}
          {bracket ? (
            <div className="space-y-3" data-testid="replay-bracket-legs">
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor={`${fieldId}-stop`}>Stop ({currency})</Label>
                  <Input
                    id={`${fieldId}-stop`}
                    name="stop_price"
                    type="number"
                    min="0"
                    step="any"
                    required
                    value={stop}
                    onChange={(event) => setStop(event.target.value)}
                    data-testid="replay-bracket-stop"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`${fieldId}-target`}>Target ({currency})</Label>
                  <Input
                    id={`${fieldId}-target`}
                    name="target_price"
                    type="number"
                    min="0"
                    step="any"
                    required
                    value={targetPrice}
                    onChange={(event) => setTargetPrice(event.target.value)}
                    data-testid="replay-bracket-target"
                  />
                </div>
              </div>
              <p className="text-2xs leading-4 text-text-tertiary">
                The stop and the target rest once the entry fills, from the next bar, and one
                cancels the other.{" "}
                {intrabar
                  ? "When both are inside one bar, the stored minutes decide; without minutes the stop fills first, labelled."
                  : "Both are checked on each later close."}
              </p>
              {bracketProblem ? (
                <p className="text-xs text-negative" data-testid="replay-bracket-problem">
                  {bracketProblem}
                </p>
              ) : null}
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
              <dd>Current stored close · {replayProfileLabel(profileName, profileVersion)}</dd>
            </div>
          </dl>
          {state.error ? (
            <p role="alert" className="text-sm text-negative">
              {state.error}
            </p>
          ) : null}
          {state.filled ? (
            <output className="block text-sm text-positive">
              Filled {titleCase(state.side)} {formatQuantity(state.quantity ?? "0")} {ticker} @{" "}
              {money(state.fillPrice ?? "0")}
            </output>
          ) : null}
          {state.placed ? (
            <output className="block text-sm text-foreground" data-testid="replay-order-placed">
              {state.orderType === "bracket"
                ? `Placed bracket ${state.side === "sell" ? "short" : "buy"} ${formatQuantity(state.quantity ?? "0")} ${ticker}: entry ${money(state.limitPrice ?? "0")}, stop ${money(state.stopPrice ?? "0")}, target ${money(state.targetPrice ?? "0")}.`
                : `Placed ${replayOrderTypeLabel(state.orderType ?? "").toLowerCase()} ${state.side} ${formatQuantity(state.quantity ?? "0")} ${ticker} at ${money(state.limitPrice ?? "0")}. It is checked from the next bar.`}
            </output>
          ) : null}
          <Button
            type="submit"
            disabled={
              pending ||
              !(qty > 0) ||
              (resting && !(Number(price) > 0)) ||
              (bracket && bracketProblem !== null)
            }
            className="w-full"
          >
            {pending
              ? "Submitting…"
              : bracket
                ? shortBracket
                  ? "Place short bracket"
                  : "Place bracket buy"
                : resting
                  ? `Place ${replayOrderTypeLabel(orderType).toLowerCase()} ${effectiveSide}`
                  : `Submit market ${effectiveSide}`}
          </Button>
        </form>
      )}
    </section>
  );
}

function defaultLevel(close: string, factor: number): string {
  const value = Number(close) * factor;
  return Number.isFinite(value) ? String(Math.round(value * 100) / 100) : "";
}

/** Why a bracket's levels cannot be placed, or null (the API checks the same). */
export function bracketLevelsProblem(
  entry: string,
  stop: string,
  target: string,
  direction: "long" | "short" = "long",
): string | null {
  const e = Number(entry);
  const s = Number(stop);
  const t = Number(target);
  if (!(s > 0) || !(t > 0)) return "Enter a positive stop and target.";
  if (!(e > 0)) return null;
  if (direction === "short") {
    if (!(t < e && e < s)) return "A short's stop must be above the entry and its target below.";
    return null;
  }
  if (!(s < e && e < t)) return "The stop must be below the entry and the target above it.";
  return null;
}

function restingHelp(orderType: string, side: "buy" | "sell", intrabar: boolean): string {
  if (intrabar) {
    if (orderType === "limit") {
      return side === "buy"
        ? "Fills when a later bar trades at or below this price (at the open if it opens there)."
        : "Fills when a later bar trades at or above this price (at the open if it opens there).";
    }
    return orderType === "stop_loss"
      ? "Sells when a later bar trades at or below this price (at the open on a gap)."
      : "Sells when a later bar trades at or above this price (at the open on a gap).";
  }
  if (orderType === "limit") {
    return side === "buy"
      ? "Fills at a later close at or below this price."
      : "Fills at a later close at or above this price.";
  }
  return orderType === "stop_loss"
    ? "Sells at a later close at or below this price."
    : "Sells at a later close at or above this price.";
}
