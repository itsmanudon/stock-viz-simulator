"use client";

import { useActionState, useState } from "react";

import { placeTradeAction } from "@/app/(authed)/trade/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  options: Array<{ ticker: string; name: string }>;
  heldTickers: string[];
};

export function TradeForm({ options, heldTickers }: Props) {
  const [state, action, pending] = useActionState(placeTradeAction, {});
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const heldSet = new Set(heldTickers);

  return (
    <Card>
      <CardContent className="p-6">
        <form action={action} className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Button
              type="button"
              variant={side === "buy" ? "default" : "outline"}
              onClick={() => setSide("buy")}
            >
              Buy
            </Button>
            <Button
              type="button"
              variant={side === "sell" ? "default" : "outline"}
              onClick={() => setSide("sell")}
            >
              Sell
            </Button>
            <input type="hidden" name="side" value={side} />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ticker">Symbol</Label>
            <select
              id="ticker"
              name="ticker"
              required
              defaultValue={heldTickers[0] ?? options[0]?.ticker ?? ""}
              className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {options.map((opt) => (
                <option key={opt.ticker} value={opt.ticker}>
                  {opt.ticker} — {opt.name}
                  {heldSet.has(opt.ticker) ? " (holding)" : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="quantity">Quantity</Label>
            <Input
              id="quantity"
              name="quantity"
              type="number"
              min="0.000001"
              step="0.000001"
              defaultValue="1"
              required
            />
            <p className="text-xs text-muted-foreground">
              Fractional shares allowed. Fills at the latest EOD close.
            </p>
          </div>

          {state.error ? (
            <p className="text-sm text-red-500" role="alert">
              {state.error}
            </p>
          ) : null}
          {state.success ? (
            <output className="block text-sm text-green-500">
              Filled {state.success.side.toUpperCase()} {state.success.quantity}{" "}
              {state.success.ticker} @ ${Number(state.success.price).toFixed(2)}
            </output>
          ) : null}

          <Button type="submit" disabled={pending} className="w-full">
            {pending ? "Placing order…" : `Place ${side} order`}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
