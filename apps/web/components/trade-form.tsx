"use client";

import { useActionState, useState } from "react";

import { placeTradeAction } from "@/app/(authed)/trade/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  options: Array<{ ticker: string; name: string; currency: string }>;
  heldTickers: string[];
};

function fmtMoney(raw: string, ccy: string): string {
  const n = Number(raw);
  const opts: Intl.NumberFormatOptions = {
    style: "currency",
    currency: ccy,
    minimumFractionDigits: ccy === "JPY" ? 0 : 2,
    maximumFractionDigits: ccy === "JPY" ? 0 : 2,
  };
  try {
    return n.toLocaleString("en-US", opts);
  } catch {
    return `${ccy} ${n.toFixed(2)}`;
  }
}

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
                  {opt.ticker} ({opt.currency}) — {opt.name}
                  {heldSet.has(opt.ticker) ? " · holding" : ""}
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
            <output className="block space-y-0.5 text-sm">
              <span className="block text-green-500">
                Filled {state.success.side.toUpperCase()} {state.success.quantity}{" "}
                {state.success.ticker} @ {fmtMoney(state.success.price, state.success.currency)}
              </span>
              <span className="block text-xs text-muted-foreground">
                Native total {fmtMoney(state.success.total_native, state.success.currency)}
                {state.success.currency !== "USD" ? (
                  <> · USD debit {fmtMoney(state.success.total_usd, "USD")}</>
                ) : null}
              </span>
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
