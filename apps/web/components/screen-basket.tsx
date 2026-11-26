"use client";

/**
 * A6.11 (M10.5): the screen's rows on this page as a basket: a market buy of
 * the same number of shares of each, for the user to enter at their broker.
 * Folded away until opened, so the results stay the page's focus.
 */

import { useId, useState } from "react";

import { BasketExport } from "@/components/basket-export";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type KiteHandoff, basketFromScreen } from "@/lib/basket";

export function ScreenBasket({ tickers, kite }: { tickers: string[]; kite: KiteHandoff }) {
  const id = useId();
  const [quantity, setQuantity] = useState(1);
  if (tickers.length === 0) return null;
  return (
    <details className="mt-4 rounded-lg border border-border-muted" data-testid="screen-basket">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-text-secondary">
        Basket From This Screen ({tickers.length} symbol{tickers.length === 1 ? "" : "s"})
      </summary>
      <div className="space-y-3 px-3 pb-3">
        <div className="flex items-end gap-2">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-qty`} className="text-xs">
              Shares of Each
            </Label>
            <Input
              id={`${id}-qty`}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
              className="h-8 w-24 font-mono"
            />
          </div>
          <p className="pb-1.5 text-2xs text-text-tertiary">Market buys, this page&apos;s rows.</p>
        </div>
        <BasketExport orders={basketFromScreen(tickers, quantity)} source="Screen" kite={kite} />
      </div>
    </details>
  );
}
