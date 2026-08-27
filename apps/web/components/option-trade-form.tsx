"use client";

/**
 * Options order ticket on /trade. Buys a call/put to open via the
 * openOptionAction server action. Closing positions happens from /portfolio.
 */

import { useActionState, useState } from "react";

import {
  type OptionTradeState,
  openOptionAction,
} from "@/app/(product)/(authed)/trade/options-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type SymbolOption = { ticker: string; name: string };

function defaultExpiry(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 30);
  return d.toISOString().slice(0, 10);
}

export function OptionTradeForm({ options }: { options: SymbolOption[] }) {
  const [state, action, pending] = useActionState<OptionTradeState, FormData>(openOptionAction, {});
  const [optionType, setOptionType] = useState<"call" | "put">("call");

  return (
    <div className="border-y border-border-muted sm:border-x">
      <form action={action} className="space-y-5 p-4">
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
        </div>

        <div className="space-y-2">
          <Label htmlFor="opt-ticker">Underlying</Label>
          <select
            id="opt-ticker"
            name="ticker"
            required
            defaultValue={options[0]?.ticker ?? ""}
            className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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
          <p className="text-sm text-red-500" role="alert">
            {state.error}
          </p>
        ) : null}
        {state.success ? (
          <output className="block text-sm text-green-500">
            Bought {state.success.quantity} {state.success.ticker}{" "}
            {state.success.option_type.toUpperCase()} @ ${Number(state.success.strike).toFixed(2)}{" "}
            for ${Number(state.success.premium_paid).toFixed(2)}
          </output>
        ) : null}

        <Button type="submit" disabled={pending} className="w-full rounded-sm">
          {pending ? "Placing order…" : `Buy ${optionType}`}
        </Button>
      </form>
    </div>
  );
}
