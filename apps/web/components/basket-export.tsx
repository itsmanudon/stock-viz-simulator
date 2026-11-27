"use client";

/**
 * A6.11 (M10.5): "take this basket to your broker". Downloads the orders as
 * CSV or JSON, and, only when the server has `KITE_API_KEY` (`kite` is not
 * null), offers Kite's offsite basket: a hidden form this browser POSTs to
 * Zerodha, where the user reviews and confirms. StockViz never places an
 * order, and the API never calls Kite for this.
 *
 * Keyboard: native buttons; the Kite form submits from its own button.
 */

import { Download, ExternalLink } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import {
  type BasketOrder,
  KITE_BASKET_URL,
  type KiteHandoff,
  basketCsv,
  basketFileName,
  basketJson,
  kiteBasketData,
  kiteEligible,
} from "@/lib/basket";

function download(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function BasketExport({
  orders,
  source,
  kite,
  className,
}: {
  orders: BasketOrder[];
  /** Names the file and the section ("Plan TCS.NS", "Rebalance", "Screen"). */
  source: string;
  kite: KiteHandoff;
  className?: string;
}) {
  const id = useId();
  if (orders.length === 0) return null;
  const kiteOrders = kiteEligible(orders).filter((o) => o.role !== "Stop" && o.role !== "Target");
  const hasExits = orders.some((o) => o.role === "Stop" || o.role === "Target");
  return (
    <section
      data-testid="basket-export"
      aria-labelledby={`${id}-title`}
      className={`space-y-2 rounded-md border border-border-muted bg-surface-secondary/40 p-3 text-xs ${className ?? ""}`}
    >
      <p id={`${id}-title`} className="font-medium text-text-primary">
        Basket for Your Broker ({orders.length} order{orders.length === 1 ? "" : "s"})
      </p>
      <p className="text-text-tertiary">
        StockViz never places an order. Download the basket and enter it at your broker.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => download(basketCsv(orders), basketFileName(source, "csv"), "text/csv")}
        >
          <Download className="size-3.5" aria-hidden /> Download CSV
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            download(basketJson(orders), basketFileName(source, "json"), "application/json")
          }
        >
          <Download className="size-3.5" aria-hidden /> Download JSON
        </Button>
        {kite && kiteOrders.length > 0 ? (
          <form
            method="post"
            action={KITE_BASKET_URL}
            target="_blank"
            data-testid="basket-kite-form"
          >
            <input type="hidden" name="api_key" value={kite.apiKey} />
            <input type="hidden" name="data" value={kiteBasketData(orders)} />
            <Button type="submit" size="sm">
              <ExternalLink className="size-3.5" aria-hidden /> Review in Kite
            </Button>
          </form>
        ) : null}
      </div>
      {kite && kiteOrders.length > 0 ? (
        <p className="text-2xs text-text-tertiary">
          Kite opens in a new tab with {kiteOrders.length} order
          {kiteOrders.length === 1 ? "" : "s"} to review and confirm inside Zerodha.
          {hasExits ? " It gets the entry only: place the stop and target once it fills." : ""}
        </p>
      ) : null}
    </section>
  );
}
