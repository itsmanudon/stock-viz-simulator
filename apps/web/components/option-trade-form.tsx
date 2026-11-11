"use client";

/**
 * Options order ticket on /trade. Buys a call/put to open via the
 * openOptionAction server action. Closing positions happens from /portfolio.
 */

import { useActionState, useEffect, useState } from "react";

import {
  type OptionTradeState,
  openOptionAction,
} from "@/app/(product)/(authed)/trade/options-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { newClientOrderId } from "@/lib/order-review";

type SymbolOption = { ticker: string; name: string };

function defaultExpiry(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 30);
  return d.toISOString().slice(0, 10);
}

export function OptionTradeForm({ options }: { options: SymbolOption[] }) {
  const [state, action, pending] = useActionState<OptionTradeState, FormData>(openOptionAction, {});
  const [optionType, setOptionType] = useState<"call" | "put">("call");
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
            defaultValue={options[0]?.ticker ?? ""}
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
              defaultValue="100"
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
              defaultValue="1"
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
            defaultValue={defaultExpiry()}
            required
          />
          <p className="text-xs text-muted-foreground">
            Premium is priced with Black-Scholes using 30-day historical volatility, not a live
            implied-vol surface. One contract covers 100 shares.
          </p>
        </div>

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
          {pending ? "Placing order…" : `Buy ${optionType}`}
        </Button>
      </form>
    </div>
  );
}
