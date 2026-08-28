"use client";

/**
 * Standalone execution ticket for /trade.
 *
 * Submits through the existing server actions. Estimated notional is
 * display-only from API decimal strings; buying power and fills stay on
 * the backend. Market orders fill at the latest stored daily close.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useActionState, useEffect, useMemo, useState } from "react";

import {
  type OrderFormState,
  type TradeFormState,
  placeOrderAction,
  placeTradeAction,
} from "@/app/(product)/(authed)/trade/actions";
import { OrderSideToggle } from "@/components/order-side-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { compareDecimalStrings, multiplyDecimalStrings } from "@/lib/decimal-math";
import { type TradeOrderMode, orderTypeLabel } from "@/lib/operational-trading";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";

export type OrderTicketSymbol = { ticker: string; name: string; currency: string };

export type OrderTicketPosition = {
  quantity: string;
  availableQuantity: string;
  reservedQuantity: string;
  averageCost: string;
  lastClose: string | null;
  currency: string;
};

type Props = {
  symbols: OrderTicketSymbol[];
  initialTicker: string;
  quoteClose: string | null;
  quoteAt: string | null;
  position: OrderTicketPosition | null;
  availableCash: string;
  displayCurrency: string;
};

function triggerCopy(mode: TradeOrderMode, side: "buy" | "sell"): string {
  if (mode === "limit" && side === "buy") {
    return "Queued until a stored daily close is at or below this price. Fill is that close, not an exchange limit fill.";
  }
  if (mode === "limit" && side === "sell") {
    return "Queued until a stored daily close is at or above this price. Fill is that close, not an exchange limit fill.";
  }
  if (mode === "stop_loss") {
    return "Sell-only. Queued until a stored daily close is at or below this trigger. Fill is that close.";
  }
  if (mode === "take_profit") {
    return "Sell-only. Queued until a stored daily close is at or above this trigger. Fill is that close.";
  }
  return "Submits immediately at the latest stored daily close. Not a live exchange fill.";
}

export function OrderTicket({
  symbols,
  initialTicker,
  quoteClose,
  quoteAt,
  position,
  availableCash,
  displayCurrency,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const known = useMemo(() => new Set(symbols.map((item) => item.ticker)), [symbols]);
  const startingTicker =
    initialTicker && known.has(initialTicker) ? initialTicker : (symbols[0]?.ticker ?? "");

  const [ticker, setTicker] = useState(startingTicker);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [mode, setMode] = useState<TradeOrderMode>("market");
  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");

  // Do not key this island from the server page. revalidatePath("/trade") after a
  // fill must keep useActionState so the fill announcement survives. Sync the
  // URL-selected ticker in instead.
  useEffect(() => {
    if (startingTicker) setTicker(startingTicker);
  }, [startingTicker]);

  const selected = symbols.find((item) => item.ticker === ticker);
  const currency = selected?.currency || "USD";
  const [marketState, marketAction, marketPending] = useActionState<TradeFormState, FormData>(
    placeTradeAction,
    {},
  );
  const [orderState, orderAction, orderPending] = useActionState<OrderFormState, FormData>(
    placeOrderAction,
    {},
  );

  const pending = marketPending || orderPending;
  const effectiveSide = mode === "stop_loss" || mode === "take_profit" ? "sell" : side;
  const referencePrice = mode === "market" ? quoteClose : limitPrice;
  const estimate = referencePrice ? multiplyDecimalStrings(quantity, referencePrice, 2) : null;
  const estimateLabel =
    mode === "market"
      ? "Estimated notional at latest stored close"
      : "Estimated notional at limit / trigger";

  function syncTicker(next: string) {
    setTicker(next);
    router.replace(`${pathname}?ticker=${encodeURIComponent(next)}`, { scroll: false });
  }

  function onModeChange(next: TradeOrderMode) {
    setMode(next);
    if (next === "stop_loss" || next === "take_profit") setSide("sell");
  }

  const action = mode === "market" ? marketAction : orderAction;
  const error = mode === "market" ? marketState.error : orderState.error;
  const marketSuccess = mode === "market" ? marketState.success : undefined;
  const orderSuccess = mode === "market" ? undefined : orderState.success;

  return (
    <section
      aria-labelledby="order-ticket-heading"
      className="border-y border-border-muted sm:border-x"
    >
      <div className="border-b border-border-muted px-4 py-3">
        <h2 id="order-ticket-heading" className="text-sm font-semibold">
          Order ticket
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          Paper execution against stored end-of-day closes. The API remains authoritative for cash,
          reservations, and fills.
        </p>
      </div>

      <form action={action} className="space-y-5 p-4">
        {mode !== "market" ? <input type="hidden" name="order_type" value={mode} /> : null}
        <input type="hidden" name="side" value={effectiveSide} />
        <input type="hidden" name="ticker" value={ticker} />

        <div className="space-y-2">
          <Label htmlFor="trade-ticker">Symbol</Label>
          <select
            id="trade-ticker"
            value={ticker}
            onChange={(event) => syncTicker(event.target.value)}
            required
            className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
          >
            {symbols.map((symbol) => (
              <option key={symbol.ticker} value={symbol.ticker}>
                {symbol.ticker} ({symbol.currency}) — {symbol.name}
              </option>
            ))}
          </select>
          {ticker ? (
            <p className="text-xs text-text-tertiary">
              <Link href={`/stocks/${ticker}`} className="hover:underline">
                Open {ticker} workspace
              </Link>
              {quoteClose ? (
                <>
                  {" "}
                  · Last stored close {formatCurrency(quoteClose, currency)}
                  {quoteAt ? ` as of ${new Date(quoteAt).toISOString().slice(0, 10)}` : ""}
                </>
              ) : (
                " · No stored close for this symbol"
              )}
            </p>
          ) : null}
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Side</legend>
          <OrderSideToggle
            side={effectiveSide}
            onChange={setSide}
            disabled={mode === "stop_loss" || mode === "take_profit"}
          />
          {mode === "stop_loss" || mode === "take_profit" ? (
            <p className="text-xs text-text-tertiary">
              {orderTypeLabel(mode)} orders are sell-only in this simulator.
            </p>
          ) : null}
        </fieldset>

        <div className="space-y-2">
          <Label htmlFor="trade-mode">Order type</Label>
          <select
            id="trade-mode"
            value={mode}
            onChange={(event) => onModeChange(event.target.value as TradeOrderMode)}
            className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
          >
            <option value="market">Market</option>
            <option value="limit">Limit</option>
            <option value="stop_loss">Stop-loss</option>
            <option value="take_profit">Take-profit</option>
          </select>
          <p className="text-xs leading-5 text-text-tertiary">{triggerCopy(mode, effectiveSide)}</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="quantity">Quantity</Label>
          <Input
            id="quantity"
            name="quantity"
            type="number"
            min="0.000001"
            step="0.000001"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
          />
          {effectiveSide === "sell" && position ? (
            <p className="text-xs text-text-tertiary">
              {formatQuantity(position.availableQuantity)} shares available after pending sells
              {compareDecimalStrings(position.reservedQuantity, "0") === 1
                ? ` (${formatQuantity(position.reservedQuantity)} reserved)`
                : ""}
              .
            </p>
          ) : null}
          {effectiveSide === "buy" ? (
            <p className="text-xs text-text-tertiary">
              Available cash {formatCurrency(availableCash, displayCurrency)} after pending buy
              reservations.
            </p>
          ) : null}
        </div>

        {mode !== "market" ? (
          <div className="space-y-2">
            <Label htmlFor="limit_price">
              {mode === "limit" ? "Limit price" : "Trigger price"}
            </Label>
            <Input
              id="limit_price"
              name="limit_price"
              type="number"
              min="0.000001"
              step="0.01"
              value={limitPrice}
              onChange={(event) => setLimitPrice(event.target.value)}
              required
            />
          </div>
        ) : null}

        <p className="text-sm">
          <span className="block text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
            {estimateLabel}
          </span>
          <span className="mt-1 block font-mono text-lg tabular-nums">
            {estimate ? formatCurrency(estimate, currency) : "—"}
          </span>
          {currency !== displayCurrency ? (
            <span className="mt-1 block text-xs text-text-tertiary">
              Native {currency} estimate. USD cash impact is computed at fill time by the API.
            </span>
          ) : (
            <span className="mt-1 block text-xs text-text-tertiary">
              Display estimate only. Submission still goes through the ledger.
            </span>
          )}
        </p>

        {error ? (
          <p className="text-sm text-negative" role="alert">
            {error}
          </p>
        ) : null}
        {marketSuccess ? (
          <output aria-live="polite" className="block text-sm text-positive">
            Filled {marketSuccess.side.toUpperCase()} {marketSuccess.quantity}{" "}
            {marketSuccess.ticker} @ {formatCurrency(marketSuccess.price, marketSuccess.currency)}
          </output>
        ) : null}
        {orderSuccess ? (
          <output aria-live="polite" className="block text-sm text-positive">
            {orderSuccess}
          </output>
        ) : null}

        <Button type="submit" disabled={pending || !ticker} className="w-full rounded-sm">
          {pending
            ? "Submitting…"
            : `Submit ${orderTypeLabel(mode).toLowerCase()} ${effectiveSide}`}
        </Button>
      </form>
    </section>
  );
}
