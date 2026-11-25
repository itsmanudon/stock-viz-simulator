"use client";

/**
 * The order review and confirmation shared by both paper tickets: the stock
 * page's ContextualTradeTicket and the /trade OrderTicket (UI audit UX-4).
 *
 * The review is laid out like Revolut's order summary: the amount first, then
 * one quiet table of everything that decides the fill. It renders the
 * quantity and price as hidden fields, so the review's own button submits
 * exactly what is shown; callers must unmount their editable inputs while it
 * is open. Callers also send `review_step` ("draft" until the review is open)
 * so the server actions can refuse a post that skipped it (lib/order-review).
 * Each opened review also posts a fresh `client_order_id`, which makes its
 * confirmation safe to repeat (#67).
 */

import { CircleCheck, Clock3 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import { LimitPreviewRows } from "@/components/limit-preview";
import { Button } from "@/components/ui/button";
import { getFeeEstimate } from "@/lib/api/fees";
import { type FeeEstimate, formatDay, sourceDated } from "@/lib/fees";
import { newClientOrderId } from "@/lib/order-review";
import { splitMinorUnits } from "@/lib/portfolio-view-model";
import {
  type TicketOrderMode,
  describeFillRule,
  formatCloseDate,
  formatQuantity,
} from "@/lib/stock-workspace";

type OrderMode = TicketOrderMode;
type Side = "buy" | "sell";

/** What the review needs to know about the account. */
export type ReviewAccount = {
  displayCurrency: string;
  availableCash: number;
};

export function formatMoney(value: number, currency: string): string {
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

/**
 * False in the server render and until hydration. Before that, a click would
 * post the form natively and bypass the review, so review buttons stay
 * disabled until this is true.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribeNoop,
    () => true,
    () => false,
  );
}

function subscribeNoop() {
  return () => {};
}

const MODE_LABEL: Record<OrderMode, string> = {
  market: "Market",
  limit: "Limit",
  stop_loss: "Stop loss",
  take_profit: "Take profit",
};

/**
 * The review step, laid out like Revolut's order summary: the amount first,
 * then one quiet table of everything that decides the fill. The quantity and
 * price stay in the form as hidden fields so the review's button submits
 * exactly what is shown.
 */
export function OrderReview({
  mode,
  side,
  ticker,
  quantity,
  triggerPrice,
  currency,
  latestClose,
  closeDate,
  notional,
  account,
  availableQuantity,
}: {
  mode: OrderMode;
  side: Side;
  ticker: string;
  quantity: string;
  triggerPrice: string;
  currency: string;
  latestClose: number | null;
  closeDate: string | null;
  notional: number | null;
  account: ReviewAccount | null;
  availableQuantity: number;
}) {
  const sign = side === "buy" ? "−" : "+";
  const closeLabel = formatCloseDate(closeDate);
  const sameCurrency = account?.displayCurrency === currency;
  const qty = Number(quantity);
  // One key per opened review: repeats of this confirmation place it once.
  const [clientOrderId] = useState(newClientOrderId);
  // A4.2: the fees this fill would pay (the ticker's default schedule, today's
  // version), net first. Stop and take-profit orders are sells.
  const feeSide: Side = mode === "market" || mode === "limit" ? side : "sell";
  const feePrice = mode === "market" ? latestClose : Number(triggerPrice);
  const fees = useFeeEstimate(ticker, feeSide, quantity, feePrice);
  const feeTotal = fees ? Number(fees.total) : null;
  const net =
    notional === null || feeTotal === null
      ? notional
      : feeSide === "buy"
        ? notional + feeTotal
        : notional - feeTotal;

  const amount = notional === null ? "—" : formatMoney(notional, currency);
  const headline = net === null ? "—" : formatMoney(net, currency);
  const [major, minor] = splitMinorUnits(headline);

  const rows: { label: string; value: string; tone?: "warning" }[] = [
    { label: "Quantity", value: `${formatQuantity(qty)} ${ticker}` },
    mode === "market"
      ? {
          label: "Reference price",
          value:
            latestClose === null
              ? "—"
              : `${formatMoney(latestClose, currency)}${closeLabel ? ` · close of ${closeLabel.replaceAll(" ", "\u00a0")}` : ""}`,
        }
      : {
          label: mode === "limit" ? "Your limit" : "Your trigger",
          value: formatMoney(Number(triggerPrice), currency),
        },
    {
      label: feeSide === "buy" ? "Estimated total, after fees" : "Estimated proceeds, after fees",
      value: net === null ? "—" : formatMoney(net, currency),
    },
    { label: "Value before fees", value: amount },
    {
      label: "Fees",
      value:
        fees === undefined
          ? "Estimating…"
          : fees === null
            ? "Not available"
            : feeTotal === 0
              ? "None for this market"
              : formatMoney(feeTotal ?? 0, currency),
    },
  ];

  if (side === "buy" && account && sameCurrency && net !== null) {
    const after = account.availableCash - net;
    rows.push(
      mode === "market"
        ? {
            label: "Buying power after",
            value: formatMoney(after, account.displayCurrency),
            tone: after < 0 ? "warning" : undefined,
          }
        : {
            label: "Cash reserved until filled",
            value: formatMoney(net, account.displayCurrency),
            tone: after < 0 ? "warning" : undefined,
          },
    );
  } else if (side === "buy" && account && !sameCurrency) {
    rows.push({
      label: "Paid in",
      value: `${account.displayCurrency}, converted at the latest stored rate`,
    });
  } else if (side === "sell") {
    rows.push({
      label: "Shares left to sell",
      value: `${formatQuantity(Math.max(availableQuantity - qty, 0))} ${ticker}`,
      tone: qty > availableQuantity ? "warning" : undefined,
    });
  }

  const overLimit = rows.some((row) => row.tone === "warning");

  return (
    <div className="space-y-4" aria-live="polite">
      <input type="hidden" name="quantity" value={quantity} />
      <input type="hidden" name="client_order_id" value={clientOrderId} />
      {mode !== "market" ? <input type="hidden" name="limit_price" value={triggerPrice} /> : null}

      <div>
        <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-text-tertiary">
          Review order
        </p>
        <p className="mt-2 font-mono text-3xl font-medium tracking-tight" data-financial>
          {notional === null ? "" : sign}
          {major}
          {minor ? <span className="figure-minor">{minor}</span> : null}
        </p>
        <p className="mt-1 text-sm text-text-secondary">
          {MODE_LABEL[mode]} {mode === "market" || mode === "limit" ? side : "sell"}{" "}
          {formatQuantity(qty)} {ticker}
        </p>
      </div>

      <dl className="divide-y divide-border-muted rounded-xl border border-border-muted bg-card text-xs">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start justify-between gap-4 px-3 py-2.5">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd
              className={`text-right font-mono tabular-nums ${row.tone === "warning" ? "text-warning" : ""}`}
            >
              {row.value}
            </dd>
          </div>
        ))}
        {fees && fees.lines.length > 0 ? (
          <div className="px-3 py-2.5" data-testid="order-costs">
            <details>
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Costs: {fees.label}
                {fees.effective_from
                  ? `, rates in force from ${formatDay(fees.effective_from)}`
                  : ""}
              </summary>
              <ul className="mt-2 space-y-1.5">
                {fees.lines.map((line) => (
                  <li key={line.key} className="flex items-start justify-between gap-3">
                    <span>
                      {line.label}
                      <span className="block text-2xs text-text-tertiary">
                        {line.rate_text}
                        {line.source ? (
                          <>
                            {" · "}
                            <a
                              href={line.source.url}
                              target="_blank"
                              rel="noreferrer"
                              className="underline underline-offset-2"
                              title={sourceDated(line.source)}
                            >
                              source
                            </a>
                          </>
                        ) : null}
                      </span>
                    </span>
                    <span className="font-mono tabular-nums">
                      {formatMoney(Number(line.amount), currency)}
                    </span>
                  </li>
                ))}
              </ul>
              {fees.dp_note ? (
                <p className="mt-2 text-2xs text-text-tertiary">{fees.dp_note}</p>
              ) : null}
              <p className="mt-2 text-2xs text-text-tertiary">
                <Link href="/docs/costs" className="underline underline-offset-2">
                  Every schedule and its sources
                </Link>
              </p>
            </details>
          </div>
        ) : null}
        <div className="px-3 py-2.5">
          <dt className="text-muted-foreground">How it fills</dt>
          <dd className="mt-1 leading-5">{describeFillRule(mode)}</dd>
        </div>
      </dl>

      {side === "buy" && (mode === "market" || mode === "limit") ? (
        <LimitPreviewRows ticker={ticker} quantity={quantity} />
      ) : null}

      {overLimit ? (
        <output className="block text-xs text-warning">
          {side === "buy"
            ? "This is more than your buying power, so the order is likely to be rejected."
            : "This is more than you have available to sell, so the order is likely to be rejected."}
        </output>
      ) : null}
      <p className="text-2xs leading-4 text-text-tertiary">Paper trade. No real money moves.</p>
    </div>
  );
}

/**
 * The fees an order would pay, from the public estimate (undefined while
 * loading, null when it failed or there is no price yet).
 */
function useFeeEstimate(
  ticker: string,
  side: Side,
  quantity: string,
  price: number | null,
): FeeEstimate | null | undefined {
  const key = `${ticker}|${side}|${quantity}|${price ?? ""}`;
  const [state, setState] = useState<{ key: string; value: FeeEstimate | null } | null>(null);
  useEffect(() => {
    if (!(Number(quantity) > 0) || price === null || !Number.isFinite(price) || price <= 0) {
      return;
    }
    const controller = new AbortController();
    getFeeEstimate({ ticker, side, quantity, price: String(price) }, controller.signal)
      .then((value) => setState({ key, value }))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setState({ key, value: null });
        return err;
      });
    return () => controller.abort();
  }, [key, ticker, side, quantity, price]);
  if (!(Number(quantity) > 0) || price === null || !Number.isFinite(price) || price <= 0) {
    return null;
  }
  return state?.key === key ? state.value : undefined;
}

/** Shown in place of the form once the order went through. */
export function OrderConfirmation({
  filled,
  message,
  onNewOrder,
}: {
  filled: boolean;
  message: string;
  onNewOrder: () => void;
}) {
  const Icon = filled ? CircleCheck : Clock3;
  return (
    <div className="space-y-5">
      <output className="flex flex-col items-center gap-3 rounded-xl border border-border-muted bg-card px-4 py-6 text-center">
        <Icon className={`size-7 ${filled ? "text-positive" : "text-brand"}`} aria-hidden />
        <span className="text-base font-semibold">
          {filled ? "Your order was filled" : "Your order was placed"}
        </span>
        <span className="text-sm text-text-secondary">{message}</span>
      </output>
      <div className="grid grid-cols-2 gap-2">
        <Button asChild variant="outline" className="h-11 rounded-full">
          <Link href={filled ? "/portfolio" : "/orders"}>
            {filled ? "View portfolio" : "View orders"}
          </Link>
        </Button>
        <Button type="button" className="h-11 rounded-full" onClick={onNewOrder}>
          New order
        </Button>
      </div>
    </div>
  );
}
