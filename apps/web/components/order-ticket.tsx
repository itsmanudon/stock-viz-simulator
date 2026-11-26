"use client";

/**
 * Standalone execution ticket for /trade.
 *
 * Submits through the existing server actions. Estimated notional is
 * display-only from API decimal strings; buying power and fills stay on
 * the backend. Market orders fill at the latest stored daily close.
 *
 * Two-step, like the stock page's ticket (UI audit UX-4): "Review …" opens
 * the shared OrderReview, only its "Place …" button submits, and a
 * confirmation replaces the form after success. `review_step` lets the
 * server refuse a post that skipped the review (lib/order-review.ts).
 */

import { feesSuffix } from "@/lib/fees";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useActionState, useEffect, useMemo, useState } from "react";

import {
  type OrderFormState,
  type TradeFormState,
  placeOrderAction,
  placeTradeAction,
} from "@/app/(product)/(authed)/trade/actions";
import { OrderConfirmation, OrderReview, useHydrated } from "@/components/order-review";
import { OrderSideToggle } from "@/components/order-side-toggle";
import { useOutcomeSound } from "@/components/sound/sound-provider";
import { type TicketBook, TicketBookLine } from "@/components/ticket-book-line";
import { PlanReview, type TicketPlanOptions, TicketPlanSection } from "@/components/ticket-plan";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { compareDecimalStrings, multiplyDecimalStrings } from "@/lib/decimal-math";
import { type TradeOrderMode, orderTypeLabel } from "@/lib/operational-trading";
import { emptyPlanForm } from "@/lib/plans";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";

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
  /**
   * A5.2: the book orders go into (posted as `book_id`), or null for the
   * default book before the book list loads.
   */
  book?: TicketBook | null;
  /** Why this ticket can't trade here (All books, archived, imported); null = it can. */
  blockedReason?: string | null;
  /** A5.4: setups and open theses for "Plan this trade" (null: pickers empty). */
  planOptions?: TicketPlanOptions | null;
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
  book = null,
  blockedReason = null,
  planOptions = null,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const blocked = Boolean(blockedReason);
  const known = useMemo(() => new Set(symbols.map((item) => item.ticker)), [symbols]);
  const startingTicker =
    initialTicker && known.has(initialTicker) ? initialTicker : (symbols[0]?.ticker ?? "");

  const [ticker, setTicker] = useState(startingTicker);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [mode, setMode] = useState<TradeOrderMode>("market");
  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [plan, setPlan] = useState(emptyPlanForm);
  // The action state keeps its last success until the next submit, so the
  // confirmation remembers which result was already dismissed.
  const [dismissed, setDismissed] = useState<unknown>(null);
  const hydrated = useHydrated();

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
    setReviewing(false);
    setPlan(emptyPlanForm());
    // Keep the other parameters (A5.2: `book`).
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("ticker", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  function onModeChange(next: TradeOrderMode) {
    setMode(next);
    setReviewing(false);
    if (next === "stop_loss" || next === "take_profit") setSide("sell");
  }

  const action = mode === "market" ? marketAction : orderAction;
  const error = mode === "market" ? marketState.error : orderState.error;
  const marketSuccess = mode === "market" ? marketState.success : undefined;
  const orderSuccess = mode === "market" ? undefined : orderState.success;
  const activeState = mode === "market" ? marketState : orderState;
  const successMessage = marketSuccess
    ? `Filled ${titleCase(marketSuccess.side)} ${marketSuccess.quantity} ${marketSuccess.ticker} @ ${formatCurrency(marketSuccess.price, marketSuccess.currency)}${feesSuffix(marketSuccess, (v, c) => formatCurrency(String(v), c))}${marketSuccess.planned ? ". Your plan locked at this fill" : ""}`
    : orderSuccess;
  const confirmed = Boolean(successMessage) && !pending && activeState !== dismissed;
  const label = `${orderTypeLabel(mode).toLowerCase()} ${effectiveSide}`;
  useOutcomeSound(successMessage, error, marketSuccess ? "fill" : "success");

  function startNewOrder() {
    setDismissed(activeState);
    setReviewing(false);
    setPlan(emptyPlanForm());
  }
  // A5.4: a plan goes with a buy (market or limit); stops are sells.
  const canPlan = effectiveSide === "buy" && (mode === "market" || mode === "limit");
  const activePlan = canPlan ? plan : { ...plan, enabled: false };

  return (
    <section
      aria-labelledby="order-ticket-heading"
      className="overflow-hidden rounded-md border border-border-muted bg-card xl:col-start-2 xl:row-span-2"
    >
      <div className="border-b border-border-muted px-5 py-4">
        <h2 id="order-ticket-heading" className="text-sm font-semibold">
          Order ticket
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          Practice trading at stored end-of-day prices. Orders use simulated funds.
        </p>
        <TicketBookLine book={book} blockedReason={blockedReason} />
      </div>

      {confirmed && successMessage ? (
        <div className="p-5">
          <OrderConfirmation
            filled={Boolean(marketSuccess)}
            message={successMessage}
            onNewOrder={startNewOrder}
          />
        </div>
      ) : (
        <form
          action={action}
          onSubmit={(event) => {
            // Native validation has already passed when submit fires, so the
            // first submit only opens the review; the review's button submits.
            if (!reviewing) {
              event.preventDefault();
              setReviewing(true);
            }
          }}
          className="space-y-5 p-5"
        >
          {mode !== "market" ? <input type="hidden" name="order_type" value={mode} /> : null}
          {book ? <input type="hidden" name="book_id" value={book.id} /> : null}
          <input type="hidden" name="side" value={effectiveSide} />
          <input type="hidden" name="ticker" value={ticker} />
          <input type="hidden" name="review_step" value={reviewing ? "confirmed" : "draft"} />

          {reviewing ? (
            <OrderReview
              mode={mode}
              side={effectiveSide}
              ticker={ticker}
              quantity={quantity}
              triggerPrice={limitPrice}
              currency={currency}
              latestClose={quoteClose ? Number(quoteClose) : null}
              closeDate={quoteAt}
              notional={estimate ? Number(estimate) : null}
              account={{ displayCurrency, availableCash: Number(availableCash) }}
              availableQuantity={Number(position?.availableQuantity ?? 0)}
              plan={
                <PlanReview
                  form={activePlan}
                  currency={currency}
                  quantity={quantity}
                  options={planOptions}
                />
              }
            />
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="trade-ticker">Symbol</Label>
                <select
                  id="trade-ticker"
                  value={ticker}
                  onChange={(event) => syncTicker(event.target.value)}
                  required
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
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
                        {/* The calendar date from the stored string: reading it
                            as local time moved Apr 4 to 2025-04-03 east of UTC
                            (UI audit T2). */}
                        {quoteAt ? ` · ${formatCloseDate(quoteAt) ?? quoteAt}` : ""}
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
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                >
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                  <option value="stop_loss">Stop-loss</option>
                  <option value="take_profit">Take-profit</option>
                </select>
                <p className="text-xs leading-5 text-text-tertiary">
                  {triggerCopy(mode, effectiveSide)}
                </p>
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
                    {formatQuantity(position.availableQuantity)} shares available after pending
                    sells
                    {compareDecimalStrings(position.reservedQuantity, "0") === 1
                      ? ` (${formatQuantity(position.reservedQuantity)} reserved)`
                      : ""}
                    .
                  </p>
                ) : null}
                {effectiveSide === "buy" ? (
                  <p className="text-xs text-text-tertiary">
                    Available cash {formatCurrency(availableCash, displayCurrency)} after pending
                    buy reservations.
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
                    min="0.01"
                    step="0.01"
                    value={limitPrice}
                    onChange={(event) => setLimitPrice(event.target.value)}
                    required
                  />
                </div>
              ) : null}

              {canPlan ? (
                <TicketPlanSection
                  form={plan}
                  onChange={setPlan}
                  ticker={ticker}
                  currency={currency}
                  referencePrice={referencePrice || null}
                  quantity={quantity}
                  options={planOptions}
                />
              ) : null}

              <p className="rounded-md border border-border-muted bg-surface-secondary/50 p-3 text-sm">
                <span className="block text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                  {titleCase(estimateLabel)}
                </span>
                <span className="mt-1 block font-mono text-lg tabular-nums">
                  {estimate ? formatCurrency(estimate, currency) : "—"}
                </span>
                {currency !== displayCurrency ? (
                  <span className="mt-1 block text-xs text-text-tertiary">
                    Estimate in {currency}. Cash conversion is calculated when the order fills.
                  </span>
                ) : (
                  <span className="mt-1 block text-xs text-text-tertiary">
                    Estimate only. Final cost is confirmed when the order fills.
                  </span>
                )}
              </p>
            </>
          )}

          {error ? (
            <p className="text-sm text-negative" role="alert">
              {error}
            </p>
          ) : null}
          {reviewing ? (
            <div className="grid grid-cols-[auto_1fr] gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-11 rounded-full px-5"
                disabled={pending}
                onClick={() => setReviewing(false)}
              >
                Edit
              </Button>
              <Button
                type="submit"
                disabled={pending || !ticker || blocked}
                className="h-11 rounded-full"
              >
                {pending ? "Submitting…" : `Place ${label}`}
              </Button>
            </div>
          ) : (
            <Button
              type="submit"
              disabled={!ticker || !hydrated || blocked}
              className="h-11 w-full rounded-full"
            >
              Review {label}
            </Button>
          )}
        </form>
      )}
    </section>
  );
}
