"use client";

import { useActionState, useState } from "react";

import {
  type OrderFormState,
  type TradeFormState,
  placeOrderAction,
  placeTradeAction,
} from "@/app/(authed)/trade/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  options: Array<{ ticker: string; name: string }>;
  heldTickers: string[];
};

type OrderMode = "market" | "limit" | "stop_loss" | "take_profit";

const ORDER_MODE_LABELS: Record<OrderMode, string> = {
  market: "Market",
  limit: "Limit",
  stop_loss: "Stop-Loss",
  take_profit: "Take-Profit",
};

function MarketOrderForm({
  options,
  heldTickers,
}: {
  options: Props["options"];
  heldTickers: string[];
}) {
  const [state, action, pending] = useActionState(placeTradeAction, {});
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const heldSet = new Set(heldTickers);

  return (
    <form action={action} className="space-y-5">
      <SidePicker side={side} onSideChange={setSide} />
      <SymbolPicker options={options} heldSet={heldSet} heldTickers={heldTickers} />
      <QuantityInput />
      <StateOutput state={state} />
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Placing order…" : `Place ${side} order`}
      </Button>
    </form>
  );
}

function AdvancedOrderForm({
  options,
  heldTickers,
  orderMode,
}: {
  options: Props["options"];
  heldTickers: string[];
  orderMode: "limit" | "stop_loss" | "take_profit";
}) {
  const [state, action, pending] = useActionState(placeOrderAction, {} as OrderFormState);
  const defaultSide = orderMode === "limit" ? "buy" : "sell";
  const [side, setSide] = useState<"buy" | "sell">(defaultSide);
  const heldSet = new Set(heldTickers);
  const label = ORDER_MODE_LABELS[orderMode];

  return (
    <form action={action} className="space-y-5">
      <input type="hidden" name="order_type" value={orderMode} />
      {orderMode === "limit" ? (
        <SidePicker side={side} onSideChange={setSide} />
      ) : (
        <>
          <input type="hidden" name="side" value="sell" />
          <p className="text-xs text-muted-foreground">{label} orders are always sell orders.</p>
        </>
      )}
      <SymbolPicker options={options} heldSet={heldSet} heldTickers={heldTickers} />
      <QuantityInput />

      <div className="space-y-2">
        <Label htmlFor="limit_price">
          {orderMode === "limit" ? "Limit price" : "Trigger price"}
        </Label>
        <Input
          id="limit_price"
          name="limit_price"
          type="number"
          min="0.000001"
          step="0.01"
          placeholder="0.00"
          required
        />
        <p className="text-xs text-muted-foreground">
          {orderMode === "limit" &&
            side === "buy" &&
            "Fills when price falls at or below this level."}
          {orderMode === "limit" &&
            side === "sell" &&
            "Fills when price rises at or above this level."}
          {orderMode === "stop_loss" && "Fills when price falls at or below this level."}
          {orderMode === "take_profit" && "Fills when price rises at or above this level."}
        </p>
      </div>

      {state.error ? (
        <p className="text-sm text-red-500" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.success ? (
        <output className="block text-sm text-green-500">{state.success}</output>
      ) : null}

      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Placing order…" : `Place ${label} order`}
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function SidePicker({
  side,
  onSideChange,
}: {
  side: "buy" | "sell";
  onSideChange: (s: "buy" | "sell") => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Button
        type="button"
        variant={side === "buy" ? "default" : "outline"}
        onClick={() => onSideChange("buy")}
      >
        Buy
      </Button>
      <Button
        type="button"
        variant={side === "sell" ? "default" : "outline"}
        onClick={() => onSideChange("sell")}
      >
        Sell
      </Button>
      <input type="hidden" name="side" value={side} />
    </div>
  );
}

function SymbolPicker({
  options,
  heldSet,
  heldTickers,
}: {
  options: Props["options"];
  heldSet: Set<string>;
  heldTickers: string[];
}) {
  return (
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
  );
}

function QuantityInput() {
  return (
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
    </div>
  );
}

function StateOutput({ state }: { state: TradeFormState }) {
  return (
    <>
      {state.error ? (
        <p className="text-sm text-red-500" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.success ? (
        <output className="block text-sm text-green-500">
          Filled {state.success.side.toUpperCase()} {state.success.quantity} {state.success.ticker}{" "}
          @ ${Number(state.success.price).toFixed(2)}
        </output>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function TradeForm({ options, heldTickers }: Props) {
  const [orderMode, setOrderMode] = useState<OrderMode>("market");

  return (
    <Card>
      <CardContent className="p-6 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="order-mode">Order type</Label>
          <select
            id="order-mode"
            value={orderMode}
            onChange={(e) => setOrderMode(e.target.value as OrderMode)}
            className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {(Object.keys(ORDER_MODE_LABELS) as OrderMode[]).map((m) => (
              <option key={m} value={m}>
                {ORDER_MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </div>

        {orderMode === "market" ? (
          <MarketOrderForm options={options} heldTickers={heldTickers} />
        ) : (
          <AdvancedOrderForm options={options} heldTickers={heldTickers} orderMode={orderMode} />
        )}
      </CardContent>
    </Card>
  );
}
