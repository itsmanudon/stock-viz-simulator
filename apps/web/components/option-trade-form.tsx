"use client";

/**
 * Options order ticket on /trade. Buys a call/put to open via the
 * openOptionAction server action. Closing positions happens from /portfolio.
 *
 * Before the buy it shows what the buy will take (audit LG-7): the spot it
 * prices from with that close's date, the volatility, the value per share and
 * the premium, from GET /v1/options/quote, which prices with the function the
 * open charges with. The strike starts at the money for the chosen symbol and
 * follows the symbol until it is edited. Only USD symbols are offered, the
 * only underlyings the API accepts.
 */

import { useActionState, useEffect, useState } from "react";

import {
  type OptionTradeState,
  openOptionAction,
} from "@/app/(product)/(authed)/trade/options-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { type OptionQuote, getOptionQuote } from "@/lib/api/option-quote";
import { newClientOrderId } from "@/lib/order-review";
import { formatCloseDate } from "@/lib/stock-workspace";

type SymbolOption = { ticker: string; name: string };

type QuoteState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; quote: OptionQuote }
  | { status: "error"; message: string };

/** How long the inputs must rest before the ticket asks for a new quote. */
const QUOTE_DELAY_MS = 300;

function defaultExpiry(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 30);
  return d.toISOString().slice(0, 10);
}

function usd(value: string | number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Number(value),
  );
}

function quoteError(error: unknown): string {
  // ApiError's message is "API <status> <path>: <body>"; the body is the
  // API's {"detail": "..."} when it refused the request.
  if (error instanceof ApiError) {
    const body = error.message.slice(error.message.indexOf(": ") + 2);
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      // fall through
    }
  }
  return "The premium could not be priced right now.";
}

export function OptionTradeForm({ options }: { options: SymbolOption[] }) {
  const [state, action, pending] = useActionState<OptionTradeState, FormData>(openOptionAction, {});
  const [optionType, setOptionType] = useState<"call" | "put">("call");
  const [ticker, setTicker] = useState(options[0]?.ticker ?? "");
  // "" until the first quote fills it at the money; edited marks it the user's.
  const [strike, setStrike] = useState("");
  const [strikeEdited, setStrikeEdited] = useState(false);
  const [quantity, setQuantity] = useState("1");
  const [expiry, setExpiry] = useState(defaultExpiry);
  const [quote, setQuote] = useState<QuoteState>({ status: "idle" });
  // One key per buy (audit LG-10): a repeat of the same submit opens one
  // contract. Made in the browser after hydration, so the server HTML has no
  // field to disagree with, and replaced after each successful buy. A form
  // posted before hydration simply carries no key.
  const [orderKey, setOrderKey] = useState<string | null>(null);
  useEffect(() => {
    // New on mount and after a success; kept after an error, so a retry of
    // the same buy reuses it.
    setOrderKey((key) => (key === null || state.success ? newClientOrderId() : key));
  }, [state.success]);

  useEffect(() => {
    const contracts = Number(quantity);
    if (!ticker || !expiry || !Number.isInteger(contracts) || contracts < 1) {
      setQuote({ status: "idle" });
      return;
    }
    if (strike !== "" && !(Number(strike) > 0)) {
      setQuote({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setQuote({ status: "loading" });
      getOptionQuote(
        {
          ticker,
          option_type: optionType,
          strike: strike || undefined,
          expiry,
          quantity: contracts,
        },
        controller.signal,
      )
        .then((result) => {
          setQuote({ status: "ready", quote: result });
          // The first quote for a symbol names the at-the-money strike.
          if (strike === "") setStrike(Number(result.strike).toFixed(2));
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setQuote({ status: "error", message: quoteError(error) });
        });
    }, QUOTE_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [ticker, optionType, strike, quantity, expiry]);

  const ready = quote.status === "ready" ? quote.quote : null;

  return (
    <div className="overflow-hidden rounded-md border border-border-muted bg-card">
      <form action={action} className="space-y-5 p-5">
        <div className="grid grid-cols-2 gap-3">
          <Button
            type="button"
            variant={optionType === "call" ? "default" : "outline"}
            onClick={() => setOptionType("call")}
          >
            Call
          </Button>
          <Button
            type="button"
            variant={optionType === "put" ? "default" : "outline"}
            onClick={() => setOptionType("put")}
          >
            Put
          </Button>
          <input type="hidden" name="option_type" value={optionType} />
          {orderKey ? <input type="hidden" name="client_order_id" value={orderKey} /> : null}
        </div>

        <div className="space-y-2">
          <Label htmlFor="opt-ticker">Underlying</Label>
          <select
            id="opt-ticker"
            name="ticker"
            required
            value={ticker}
            onChange={(event) => {
              setTicker(event.target.value);
              // A strike the user did not set follows the new symbol's spot.
              if (!strikeEdited) setStrike("");
            }}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {options.map((opt) => (
              <option key={opt.ticker} value={opt.ticker}>
                {opt.ticker} — {opt.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="opt-strike">Strike</Label>
            <Input
              id="opt-strike"
              name="strike"
              type="number"
              min="0.01"
              step="0.01"
              value={strike}
              placeholder="At the money"
              onChange={(event) => {
                setStrike(event.target.value);
                setStrikeEdited(event.target.value !== "");
              }}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="opt-quantity">Contracts</Label>
            <Input
              id="opt-quantity"
              name="quantity"
              type="number"
              min="1"
              step="1"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              required
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="opt-expiry">Expiry</Label>
          <Input
            id="opt-expiry"
            name="expiry"
            type="date"
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
            required
          />
          <p className="text-xs text-muted-foreground">
            Premium is priced with Black-Scholes using 30-day historical volatility, not a live
            implied-vol surface. One contract covers 100 shares.
          </p>
        </div>

        <QuotePreview quote={quote} />

        {state.error ? (
          <p className="text-sm text-negative" role="alert">
            {state.error}
          </p>
        ) : null}
        {state.success ? (
          <output className="block text-sm text-positive">
            Bought {state.success.quantity} {state.success.ticker}{" "}
            {state.success.option_type.toUpperCase()} @ ${Number(state.success.strike).toFixed(2)}{" "}
            for ${Number(state.success.premium_paid).toFixed(2)}
          </output>
        ) : null}

        <Button type="submit" disabled={pending} className="w-full">
          {pending
            ? "Placing order…"
            : ready
              ? `Buy ${optionType} for ${usd(ready.premium)}`
              : `Buy ${optionType}`}
        </Button>
      </form>
    </div>
  );
}

/** The quote the buy will be charged by, or why there is none. */
function QuotePreview({ quote }: { quote: QuoteState }) {
  if (quote.status === "idle") return null;
  if (quote.status === "error") {
    return <output className="block text-sm text-warning">{quote.message}</output>;
  }
  const ready = quote.status === "ready" ? quote.quote : null;
  const closeDate = ready ? formatCloseDate(ready.spot_at) : null;
  const rows: { label: string; value: string }[] = ready
    ? [
        {
          label: "Spot",
          value: `${usd(ready.spot)}${closeDate ? ` · close of ${closeDate}` : ""}`,
        },
        {
          label: "Volatility (30-day historical)",
          value: `${(ready.volatility * 100).toFixed(1)}%`,
        },
        { label: "Value per share", value: usd(ready.per_share) },
        {
          label: "Premium",
          value: `${usd(ready.premium)} for ${ready.quantity} × ${ready.contract_size} shares`,
        },
      ]
    : [];
  return (
    <section
      aria-label="Option quote"
      aria-busy={quote.status === "loading"}
      className="rounded-md border border-border-muted px-3 py-2.5 text-xs"
    >
      {ready ? (
        <dl className="space-y-1.5">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-3">
              <dt className="text-text-tertiary">{row.label}</dt>
              <dd className="text-right font-mono tabular-nums" data-financial>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-text-tertiary">Pricing…</p>
      )}
    </section>
  );
}
