"use client";

/**
 * Strategy builder on /trade (Phase 9.5). Pick a template, an underlying,
 * strikes (they start around today's close and can be edited), expiry and
 * contracts; the server prices every leg and returns the payoff, which is
 * drawn with the figures beside it. Placing is two-step (UX-4): "Review
 * strategy" lists the legs and the cash, and only the review's button posts,
 * with a fresh client key per strategy (LG-10). Every leg opens or none do.
 */

import { type TicketBook, TicketBookLine } from "@/components/ticket-book-line";
import { useActionState, useEffect, useState } from "react";

import {
  type StrategyTradeState,
  openStrategyAction,
} from "@/app/(product)/(authed)/trade/options-actions";
import { useHydrated } from "@/components/order-review";
import { PayoffChart } from "@/components/payoff-chart";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VolatilitySmile } from "@/components/volatility-smile";
import { ApiError } from "@/lib/api/client";
import { getOptionQuote } from "@/lib/api/option-quote";
import {
  STRATEGY_TEMPLATES,
  type StrategyKind,
  type StrategyPayoff,
  defaultStrikes,
  getStrategyPayoff,
} from "@/lib/api/option-strategies";
import { newClientOrderId } from "@/lib/order-review";

type SymbolOption = { ticker: string; name: string };

type PayoffState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; payoff: StrategyPayoff }
  | { status: "error"; message: string };

const DELAY_MS = 350;

function isoInDays(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function usd(value: string | number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Number(value),
  );
}

function signedUsd(value: string | number): string {
  const n = Number(value);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(Math.abs(n))}`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.message.slice(error.message.indexOf(": ") + 2);
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      // fall through
    }
  }
  return "The strategy could not be priced right now.";
}

export function StrategyBuilder({
  options,
  book = null,
  blockedReason = null,
}: {
  options: SymbolOption[];
  /** A5.2: the book the strategy opens in; `blockedReason` disables it. */
  book?: TicketBook | null;
  blockedReason?: string | null;
}) {
  const [state, action, pending] = useActionState<StrategyTradeState, FormData>(
    openStrategyAction,
    {},
  );
  const hydrated = useHydrated();
  const [kind, setKind] = useState<StrategyKind>("bull_call");
  const [ticker, setTicker] = useState(options[0]?.ticker ?? "");
  const [spot, setSpot] = useState<number | null>(null);
  const [strikes, setStrikes] = useState<string[]>([]);
  const [expiry, setExpiry] = useState(() => isoInDays(30));
  const [farExpiry, setFarExpiry] = useState(() => isoInDays(90));
  const [optionType, setOptionType] = useState<"call" | "put">("call");
  const [quantity, setQuantity] = useState("1");
  const [payoff, setPayoff] = useState<PayoffState>({ status: "idle" });
  // A7.9: the what-if (days on, IV shift in points); blank days = off.
  const [whatIfDays, setWhatIfDays] = useState("");
  const [whatIfIv, setWhatIfIv] = useState("0");
  const [reviewing, setReviewing] = useState(false);
  const [orderKey, setOrderKey] = useState<string | null>(null);

  const template = STRATEGY_TEMPLATES.find((t) => t.kind === kind) ?? STRATEGY_TEMPLATES[0];

  useEffect(() => {
    setOrderKey((key) => (key === null || state.success ? newClientOrderId() : key));
    if (state.success) setReviewing(false);
  }, [state.success]);

  // Today's close for the symbol, from an at-the-money quote, sets the strikes.
  useEffect(() => {
    if (!ticker) return;
    const controller = new AbortController();
    getOptionQuote(
      { ticker, option_type: "call", expiry: isoInDays(30), quantity: 1 },
      controller.signal,
    )
      .then((quote) => setSpot(Number(quote.spot)))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setSpot(null);
        setPayoff({ status: "error", message: errorText(error) });
      });
    return () => controller.abort();
  }, [ticker]);

  useEffect(() => {
    if (spot !== null) setStrikes(defaultStrikes(kind, spot));
  }, [kind, spot]);

  useEffect(() => {
    const contracts = Number(quantity);
    if (!ticker || strikes.length !== template.strikes.length) return;
    if (!Number.isInteger(contracts) || contracts < 1 || strikes.some((k) => !(Number(k) > 0))) {
      setPayoff({ status: "idle" });
      return;
    }
    setReviewing(false);
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setPayoff({ status: "loading" });
      getStrategyPayoff(
        {
          kind,
          ticker,
          strikes,
          expiry,
          quantity: contracts,
          ...(kind === "calendar" ? { far_expiry: farExpiry, option_type: optionType } : {}),
        },
        controller.signal,
        whatIfDays.trim() || Number(whatIfIv)
          ? {
              daysForward: whatIfDays.trim() ? Math.max(0, Number(whatIfDays) || 0) : 0,
              ivShift: (Number(whatIfIv) || 0) / 100,
            }
          : undefined,
      )
        .then((result) => setPayoff({ status: "ready", payoff: result }))
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setPayoff({ status: "error", message: errorText(error) });
        });
    }, DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [
    kind,
    ticker,
    strikes,
    expiry,
    farExpiry,
    optionType,
    quantity,
    template.strikes.length,
    whatIfDays,
    whatIfIv,
  ]);

  const ready = payoff.status === "ready" ? payoff.payoff : null;

  return (
    <section
      aria-label="Strategy builder"
      className="overflow-hidden rounded-md border border-border-muted bg-card"
    >
      <div className="px-5 pt-4">
        <TicketBookLine book={book} blockedReason={blockedReason} />
      </div>
      <form action={action} className="space-y-5 p-5">
        {book ? <input type="hidden" name="book_id" value={book.id} /> : null}
        <input type="hidden" name="review_step" value={reviewing ? "confirmed" : "draft"} />
        {orderKey ? <input type="hidden" name="client_order_id" value={orderKey} /> : null}
        <input type="hidden" name="kind" value={kind} />

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="strat-kind">Strategy</Label>
            <select
              id="strat-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value as StrategyKind)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {STRATEGY_TEMPLATES.map((t) => (
                <option key={t.kind} value={t.kind}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="strat-ticker">Underlying</Label>
            <select
              id="strat-ticker"
              name="ticker"
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {options.map((opt) => (
                <option key={opt.ticker} value={opt.ticker}>
                  {opt.ticker} — {opt.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-xs text-text-tertiary">{template.summary}</p>

        <fieldset className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <legend className="sr-only">Strikes, low to high</legend>
          {template.strikes.map((label, i) => (
            <div key={`${kind}-${label}`} className="space-y-2">
              <Label htmlFor={`strat-strike-${i}`}>{label}</Label>
              <Input
                id={`strat-strike-${i}`}
                name="strike"
                type="number"
                min="0.01"
                step="0.01"
                value={strikes[i] ?? ""}
                onChange={(event) =>
                  setStrikes((current) =>
                    current.map((value, j) => (j === i ? event.target.value : value)),
                  )
                }
                required
              />
            </div>
          ))}
        </fieldset>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="strat-expiry">{kind === "calendar" ? "Near expiry" : "Expiry"}</Label>
            <Input
              id="strat-expiry"
              name="expiry"
              type="date"
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
              required
            />
          </div>
          {kind === "calendar" ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="strat-far">Far expiry</Label>
                <Input
                  id="strat-far"
                  name="far_expiry"
                  type="date"
                  value={farExpiry}
                  onChange={(event) => setFarExpiry(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="strat-type">Calls or puts</Label>
                <select
                  id="strat-type"
                  name="option_type"
                  value={optionType}
                  onChange={(event) => setOptionType(event.target.value as "call" | "put")}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                >
                  <option value="call">Calls</option>
                  <option value="put">Puts</option>
                </select>
              </div>
            </>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="strat-qty">Contracts</Label>
            <Input
              id="strat-qty"
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

        <div className="grid grid-cols-2 gap-2" data-testid="what-if">
          <label className="space-y-1 text-xs">
            <span className="text-text-tertiary">What-if: days from today</span>
            <input
              className="h-9 w-full rounded-md border border-border-muted bg-background px-2 text-sm"
              inputMode="numeric"
              placeholder="off"
              value={whatIfDays}
              onChange={(e) => setWhatIfDays(e.target.value)}
            />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-text-tertiary">IV shift (points)</span>
            <input
              className="h-9 w-full rounded-md border border-border-muted bg-background px-2 text-sm"
              inputMode="decimal"
              value={whatIfIv}
              onChange={(e) => setWhatIfIv(e.target.value)}
            />
          </label>
        </div>
        {payoff.status === "error" ? (
          <output className="block text-sm text-warning">{payoff.message}</output>
        ) : null}
        {payoff.status === "loading" ? (
          <p className="text-xs text-text-tertiary">Pricing the legs…</p>
        ) : null}
        {ready ? <StrategyFigures payoff={ready} /> : null}
        <details className="rounded-md border border-border-muted px-3 py-2.5">
          <summary className="cursor-pointer text-xs text-text-secondary">Volatility smile</summary>
          <div className="mt-2.5">
            <VolatilitySmile ticker={ticker} />
          </div>
        </details>

        {state.error ? (
          <p className="text-sm text-negative" role="alert">
            {state.error}
          </p>
        ) : null}
        {state.success ? (
          <output className="block text-sm text-positive">
            Opened a {state.success.label.toLowerCase()} on {state.success.ticker}:{" "}
            {Number(state.success.cash_delta) >= 0 ? "received" : "paid"}{" "}
            {usd(Math.abs(Number(state.success.cash_delta)))}.
          </output>
        ) : null}

        {reviewing && ready ? (
          <fieldset
            className="space-y-3 rounded-md border border-border px-3 py-3 text-xs"
            aria-label="Strategy review"
          >
            <p>
              Opens {ready.quote.legs.length} leg{ready.quote.legs.length === 1 ? "" : "s"} together
              at these prices, or none. Net{" "}
              {Number(ready.quote.risk.net_premium) >= 0 ? "received" : "paid"}:{" "}
              {usd(Math.abs(Number(ready.quote.risk.net_premium)))}.
              {Number(ready.quote.risk.collateral) > 0
                ? ` Cash held back while open: ${usd(ready.quote.risk.collateral)}.`
                : ""}
            </p>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => setReviewing(false)}>
                Edit
              </Button>
              <Button type="submit" disabled={pending || !hydrated || Boolean(blockedReason)}>
                {pending ? "Placing…" : `Place ${ready.quote.label.toLowerCase()}`}
              </Button>
            </div>
          </fieldset>
        ) : (
          <Button
            type="button"
            className="w-full"
            disabled={!ready || !hydrated || Boolean(blockedReason)}
            onClick={() => setReviewing(true)}
          >
            Review strategy
          </Button>
        )}
      </form>
    </section>
  );
}

function StrategyFigures({ payoff }: { payoff: StrategyPayoff }) {
  const { quote } = payoff;
  const risk = quote.risk;
  const rows = [
    {
      label: Number(risk.net_premium) >= 0 ? "Net premium received" : "Net premium paid",
      value: usd(Math.abs(Number(risk.net_premium))),
    },
    ...(Number(risk.collateral) > 0
      ? [{ label: "Cash held back", value: usd(risk.collateral) }]
      : []),
    ...(Number(risk.shares_reserved) > 0
      ? [{ label: "Shares used", value: `${Number(risk.shares_reserved)} ${quote.ticker}` }]
      : []),
    { label: "Most it can lose", value: usd(risk.max_loss) },
    {
      label: "Most it can gain",
      value: risk.max_gain === null ? "Not capped or not stated" : usd(risk.max_gain),
    },
    {
      label: "Breakevens at expiry",
      value: risk.breakevens.length ? risk.breakevens.map((b) => usd(b)).join(", ") : "—",
    },
    {
      label: "Chance of profit (model)",
      value: payoff.prob_profit === null ? "—" : `${(payoff.prob_profit * 100).toFixed(0)}%`,
    },
  ];
  return (
    <section aria-label="Strategy figures" className="space-y-4">
      <table className="w-full text-xs">
        <caption className="sr-only">Legs</caption>
        <thead>
          <tr className="text-left text-text-tertiary">
            <th className="font-normal">Leg</th>
            <th className="text-right font-normal">Strike</th>
            <th className="text-right font-normal">Expiry</th>
            <th className="text-right font-normal">Per share</th>
          </tr>
        </thead>
        <tbody>
          {quote.legs.map((leg) => (
            <tr key={`${leg.side}-${leg.option_type}-${leg.strike}-${leg.expiry}`}>
              <td>
                {leg.side === "long" ? "Buy" : "Write"} {leg.option_type}
              </td>
              <td className="text-right font-mono" data-financial>
                {usd(leg.strike)}
              </td>
              <td className="text-right font-mono" data-financial>
                {leg.expiry}
              </td>
              <td className="text-right font-mono" data-financial>
                {signedUsd(leg.side === "long" ? `-${leg.per_share}` : leg.per_share)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <PayoffChart
        points={payoff.points}
        spot={Number(quote.spot)}
        breakevens={risk.breakevens.map(Number)}
        horizon={payoff.horizon}
      />
      <dl className="space-y-1.5 text-xs">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-text-tertiary">{row.label}</dt>
            <dd className="text-right font-mono tabular-nums" data-financial>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-2xs text-text-tertiary">
        {risk.basis}. Each leg is priced with Black-Scholes on the implied volatility of the nearest
        listed contract in the latest stored option chain, or on 30-day historical volatility where
        none is stored; the chance of profit is a model figure at{" "}
        {(payoff.volatility * 100).toFixed(1)}% volatility.
      </p>
    </section>
  );
}
