"use client";

import Link from "next/link";
import { useActionState, useId, useState } from "react";

import {
  type OrderFormState,
  type TradeFormState,
  placeOrderAction,
  placeTradeAction,
} from "@/app/(product)/(authed)/trade/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  estimateNotional,
  formatQuantity,
  getBuyShortcutQuantity,
  getSellShortcutQuantity,
} from "@/lib/stock-workspace";

export type TicketPosition = {
  quantity: number;
  availableQuantity: number;
  averageCost: number;
  marketValue: number;
  unrealizedPnl: number;
  returnPct: number | null;
  allocationPct: number | null;
};

export type TradeTicketAccount = {
  displayCurrency: string;
  availableCash: number;
  position: TicketPosition | null;
};

type OrderMode = "market" | "limit" | "stop_loss" | "take_profit";
type Side = "buy" | "sell";

export type ContextualTradeTicketProps = {
  ticker: string;
  name: string;
  currency: string;
  latestClose: number | null;
  signedIn: boolean;
  account: TradeTicketAccount | null;
  callbackUrl: string;
  initialSide?: Side;
  openOrderCount?: number | null;
};

const SHORTCUTS = [
  { label: "25%", fraction: 0.25 },
  { label: "50%", fraction: 0.5 },
  { label: "75%", fraction: 0.75 },
  { label: "Max", fraction: 1 },
] as const;

function formatMoney(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function stateError(marketState: TradeFormState, orderState: OrderFormState, mode: OrderMode) {
  return mode === "market" ? marketState.error : orderState.error;
}

export function ContextualTradeTicket({
  ticker,
  name,
  currency,
  latestClose,
  signedIn,
  account,
  callbackUrl,
  initialSide = "buy",
  openOrderCount = 0,
}: ContextualTradeTicketProps) {
  const fieldId = useId();
  const [side, setSide] = useState<Side>(initialSide);
  const [orderMode, setOrderMode] = useState<OrderMode>("market");
  const [quantity, setQuantity] = useState("1");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [marketState, marketAction, marketPending] = useActionState<TradeFormState, FormData>(
    placeTradeAction,
    {},
  );
  const [orderState, orderAction, orderPending] = useActionState<OrderFormState, FormData>(
    placeOrderAction,
    {},
  );

  if (!signedIn) {
    return (
      <section aria-labelledby={`${fieldId}-title`} className="space-y-5">
        <TicketHeading id={`${fieldId}-title`} ticker={ticker} />
        <div className="border-y border-border-muted py-5">
          <p className="text-sm font-medium">Research first. Simulate when you are ready.</p>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            Sign in to use your paper balance, review holdings, and place an order for {name}.
          </p>
        </div>
        <Button asChild className="w-full">
          <Link
            href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
            aria-label={`Sign in to trade ${ticker}`}
          >
            Sign in to paper trade
          </Link>
        </Button>
        <p className="text-xs leading-5 text-text-tertiary">
          Research data remains available without an account.
        </p>
      </section>
    );
  }

  const position = account?.position ?? null;
  const availableQuantity = position?.availableQuantity ?? 0;
  const canProtect = availableQuantity > 0;
  const isProtective = orderMode === "stop_loss" || orderMode === "take_profit";
  const effectiveSide: Side = isProtective ? "sell" : side;
  const effectivePrice = orderMode === "market" ? latestClose : Number(triggerPrice);
  const notional = estimateNotional(Number(quantity), effectivePrice ?? Number.NaN);
  const sameCurrency = account?.displayCurrency === currency;
  const pending = orderMode === "market" ? marketPending : orderPending;
  const error = stateError(marketState, orderState, orderMode);
  const formAction = orderMode === "market" ? marketAction : orderAction;

  const marketSuccess = marketState.success;
  const successMessage =
    orderMode === "market" && marketSuccess
      ? `Filled ${marketSuccess.side.toUpperCase()} ${marketSuccess.quantity} ${marketSuccess.ticker}`
      : orderMode !== "market"
        ? orderState.success
        : undefined;

  const buyingPower = account
    ? formatMoney(account.availableCash, account.displayCurrency)
    : "Unavailable";

  const shortcutValues = SHORTCUTS.map((shortcut) => ({
    ...shortcut,
    quantity:
      effectiveSide === "sell"
        ? getSellShortcutQuantity({
            availableQuantity,
            fraction: shortcut.fraction,
          })
        : account && effectivePrice
          ? getBuyShortcutQuantity({
              availableCash: account.availableCash,
              price: effectivePrice,
              fraction: shortcut.fraction,
              symbolCurrency: currency,
              displayCurrency: account.displayCurrency,
            })
          : null,
  }));

  function chooseMode(mode: OrderMode) {
    setOrderMode(mode);
    if (mode === "stop_loss" || mode === "take_profit") setSide("sell");
  }

  return (
    <section aria-labelledby={`${fieldId}-title`} className="space-y-5">
      <TicketHeading id={`${fieldId}-title`} ticker={ticker} />

      {position ? (
        <div className="flex items-center justify-between gap-3 border-y border-border-muted py-3 text-xs">
          <div>
            <p className="text-muted-foreground">Current position</p>
            <p className="mt-0.5 font-mono font-medium tabular-nums">
              {formatQuantity(position.quantity)} shares
            </p>
          </div>
          <div className="text-right">
            <p className={position.unrealizedPnl >= 0 ? "text-positive" : "text-negative"}>
              <span className="font-mono font-semibold tabular-nums">
                {position.unrealizedPnl > 0 ? "+" : ""}
                {formatMoney(position.unrealizedPnl, account?.displayCurrency ?? currency)}
              </span>
            </p>
            {openOrderCount === null ? (
              <p className="mt-0.5 text-warning">Orders unavailable</p>
            ) : openOrderCount ? (
              <p className="mt-0.5 text-text-tertiary">
                {openOrderCount} open {openOrderCount === 1 ? "order" : "orders"}
              </p>
            ) : null}
          </div>
        </div>
      ) : openOrderCount === null ? (
        <p className="border-y border-border-muted py-3 text-xs text-warning">
          Open-order context is temporarily unavailable.
        </p>
      ) : openOrderCount ? (
        <p className="border-y border-border-muted py-3 text-xs text-muted-foreground">
          {openOrderCount} open {openOrderCount === 1 ? "order" : "orders"} for {ticker}
        </p>
      ) : null}

      <form action={formAction} className="space-y-5">
        <input type="hidden" name="ticker" value={ticker} />
        <input type="hidden" name="side" value={effectiveSide} />
        {orderMode !== "market" ? (
          <input type="hidden" name="order_type" value={orderMode} />
        ) : null}

        <div
          className="grid grid-cols-2 gap-1 rounded-md bg-surface-secondary p-1"
          aria-label="Order side"
        >
          {(["buy", "sell"] as const).map((value) => {
            const active = effectiveSide === value;
            return (
              <button
                key={value}
                type="button"
                disabled={isProtective}
                aria-pressed={active}
                onClick={() => setSide(value)}
                className={`h-9 rounded-sm border text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                  active
                    ? value === "buy"
                      ? "border-positive/40 bg-positive/10 text-positive"
                      : "border-negative/40 bg-negative/10 text-negative"
                    : "border-transparent text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                }`}
              >
                {value === "buy" ? "Buy" : "Sell"}
              </button>
            );
          })}
        </div>

        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-[0.12em] text-text-tertiary">
            Order type
          </legend>
          <div className="grid grid-cols-2 gap-2">
            {(["market", "limit"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={orderMode === mode}
                onClick={() => chooseMode(mode)}
                className={`h-8 rounded-sm border px-3 text-xs font-medium transition-colors ${
                  orderMode === mode
                    ? "border-brand/50 bg-brand/10 text-foreground"
                    : "border-border-muted text-muted-foreground hover:bg-surface-hover"
                }`}
              >
                {mode === "market" ? "Market" : "Limit"}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <Label htmlFor={`${fieldId}-quantity`}>Quantity</Label>
            {effectiveSide === "sell" && position ? (
              <span className="font-mono text-xs text-muted-foreground">
                {formatQuantity(availableQuantity)} available
              </span>
            ) : null}
          </div>
          <Input
            id={`${fieldId}-quantity`}
            name="quantity"
            type="number"
            inputMode="decimal"
            min="0.000001"
            step="0.000001"
            required
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            className="font-mono tabular-nums"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? `${fieldId}-error` : undefined}
          />
          {shortcutValues.some((shortcut) => shortcut.quantity !== null) ? (
            <div className="grid grid-cols-4 gap-1.5">
              {shortcutValues.map((shortcut) => (
                <button
                  key={shortcut.label}
                  type="button"
                  disabled={shortcut.quantity === null}
                  onClick={() => shortcut.quantity && setQuantity(shortcut.quantity)}
                  aria-label={
                    shortcut.fraction === 1 && effectiveSide === "sell"
                      ? "Use maximum available shares"
                      : effectiveSide === "buy"
                        ? `Use ${shortcut.label} of buying power`
                        : `Use ${shortcut.label} of available shares`
                  }
                  className="h-7 rounded-sm border border-border-muted font-mono text-[11px] text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground disabled:hidden"
                >
                  {shortcut.label}
                </button>
              ))}
            </div>
          ) : effectiveSide === "buy" && account && !sameCurrency ? (
            <p className="text-xs leading-5 text-muted-foreground">
              Percentage sizing is hidden because currency conversion is unavailable for this order.
            </p>
          ) : null}
        </div>

        {orderMode !== "market" ? (
          <div className="space-y-2">
            <Label htmlFor={`${fieldId}-price`}>
              {orderMode === "limit" ? "Limit price" : "Trigger price"}
            </Label>
            <div className="relative">
              <Input
                id={`${fieldId}-price`}
                name="limit_price"
                type="number"
                inputMode="decimal"
                min="0.000001"
                step="0.01"
                required
                value={triggerPrice}
                onChange={(event) => setTriggerPrice(event.target.value)}
                placeholder="0.00"
                className="pr-14 font-mono tabular-nums"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${fieldId}-error` : undefined}
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-text-tertiary">
                {currency}
              </span>
            </div>
          </div>
        ) : null}

        <dl className="space-y-2 border-y border-border-muted py-3 text-xs">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">
              {effectiveSide === "buy" ? "Buying power" : "Available to sell"}
            </dt>
            <dd className="font-mono tabular-nums">
              {effectiveSide === "buy"
                ? buyingPower
                : `${formatQuantity(availableQuantity)} ${ticker}`}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Estimated value</dt>
            <dd className="font-mono text-sm font-semibold tabular-nums">
              {notional === null ? "—" : formatMoney(notional, currency)}
            </dd>
          </div>
          <p className="text-right text-[11px] leading-4 text-text-tertiary">
            {orderMode === "market"
              ? "Estimated at the latest cached close"
              : orderMode === "limit"
                ? "Estimated at your limit price"
                : "Estimated at your trigger price"}
          </p>
        </dl>

        {error ? (
          <p id={`${fieldId}-error`} className="text-sm text-negative" role="alert">
            {error}
          </p>
        ) : null}
        {successMessage ? (
          <output className="block text-sm text-positive">{successMessage}</output>
        ) : null}
        {!account ? (
          <output className="block text-sm text-warning">
            Account balances are temporarily unavailable. Order entry is disabled.
          </output>
        ) : null}

        <Button type="submit" disabled={pending || !account} className="w-full">
          {pending ? "Placing order…" : `Place ${effectiveSide === "buy" ? "buy" : "sell"} order`}
        </Button>
      </form>

      {canProtect ? (
        <details className="group border-t border-border-muted pt-4">
          <summary className="cursor-pointer list-none text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
            Protect position
          </summary>
          <p className="mt-2 text-xs leading-5 text-text-tertiary">
            Create a sell trigger against your {formatQuantity(availableQuantity)} available shares.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button
              type="button"
              size="sm"
              variant={orderMode === "stop_loss" ? "secondary" : "outline"}
              onClick={() => chooseMode("stop_loss")}
            >
              Stop loss
            </Button>
            <Button
              type="button"
              size="sm"
              variant={orderMode === "take_profit" ? "secondary" : "outline"}
              onClick={() => chooseMode("take_profit")}
            >
              Take profit
            </Button>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function TicketHeading({ id, ticker }: { id: string; ticker: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-brand">
          Simulation
        </p>
        <h2 id={id} className="mt-1 text-base font-semibold tracking-tight">
          Paper trade
        </h2>
      </div>
      <span className="rounded-sm bg-surface-secondary px-2 py-1 font-mono text-xs font-semibold tabular-nums">
        {ticker}
      </span>
    </div>
  );
}
