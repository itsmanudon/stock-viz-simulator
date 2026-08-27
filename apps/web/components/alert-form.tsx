"use client";

import { Bell } from "lucide-react";
import { Popover } from "radix-ui";
import { useActionState, useId, useState } from "react";

import { type CreateAlertState, createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatCurrency } from "@/lib/portfolio-view-model";

function AlertFields({
  ticker,
  tickerEditable,
  lastClose,
  currency,
  fieldId,
  pending,
  state,
  direction,
  onDirection,
}: {
  ticker: string;
  tickerEditable: boolean;
  lastClose: string | null;
  currency: string;
  fieldId: string;
  pending: boolean;
  state: CreateAlertState;
  direction: "above" | "below";
  onDirection: (value: "above" | "below") => void;
}) {
  return (
    <>
      {tickerEditable ? (
        <div className="space-y-1.5">
          <Label htmlFor={`${fieldId}-ticker`} className="text-xs">
            Symbol
          </Label>
          <Input
            id={`${fieldId}-ticker`}
            name="ticker"
            defaultValue={ticker}
            maxLength={16}
            required
            className="font-mono uppercase"
          />
        </div>
      ) : (
        <input type="hidden" name="ticker" value={ticker} />
      )}
      <div className="space-y-1.5">
        <Label htmlFor={`${fieldId}-direction`} className="text-xs">
          Notify when stored close is
        </Label>
        <select
          id={`${fieldId}-direction`}
          name="direction"
          value={direction}
          onChange={(event) => onDirection(event.target.value as "above" | "below")}
          className="h-9 w-full rounded-sm border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="above">at or above</option>
          <option value="below">at or below</option>
        </select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${fieldId}-target`} className="text-xs">
          Target price
        </Label>
        <Input
          id={`${fieldId}-target`}
          name="target_price"
          type="number"
          inputMode="decimal"
          min="0.01"
          step="0.01"
          required
          className="font-mono"
        />
        {lastClose ? (
          <p className="text-xs text-text-tertiary">
            Current stored close: {formatCurrency(lastClose, currency)}. Evaluated when daily bars
            refresh — not a real-time stream.
          </p>
        ) : (
          <p className="text-xs text-text-tertiary">
            Compared against the latest stored daily close when bars refresh.
          </p>
        )}
      </div>
      {state.error ? (
        <p className="text-xs text-negative" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.createdId ? <output className="block text-xs text-positive">Alert set.</output> : null}
      <Button type="submit" size="sm" className="rounded-sm" disabled={pending}>
        {pending ? "Saving…" : "Create alert"}
      </Button>
    </>
  );
}

export function AlertForm({
  ticker,
  lastClose = null,
  currency = "USD",
  variant = "popover",
}: {
  ticker: string;
  lastClose?: string | null;
  currency?: string;
  variant?: "popover" | "inline";
}) {
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<CreateAlertState, FormData>(
    createAlertAction,
    {},
  );
  const [direction, setDirection] = useState<"above" | "below">("above");

  if (variant === "inline") {
    return (
      <form action={action} className="space-y-3">
        <AlertFields
          ticker={ticker}
          tickerEditable={!ticker}
          lastClose={lastClose}
          currency={currency}
          fieldId={fieldId}
          pending={pending}
          state={state}
          direction={direction}
          onDirection={setDirection}
        />
      </form>
    );
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Bell className="h-4 w-4" aria-hidden />
          <span className="ml-1.5">Alert</span>
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-[min(20rem,calc(100vw-2rem))] rounded-md border border-border-muted bg-popover p-4 shadow-xl outline-none"
          aria-label={`Set a price alert for ${ticker}`}
        >
          <div className="mb-4">
            <p className="text-sm font-semibold">Price alert</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Notify me when {ticker}&apos;s stored daily close reaches a target.
            </p>
          </div>
          <form action={action} className="space-y-3">
            <AlertFields
              ticker={ticker}
              tickerEditable={false}
              lastClose={lastClose}
              currency={currency}
              fieldId={fieldId}
              pending={pending}
              state={state}
              direction={direction}
              onDirection={setDirection}
            />
          </form>
          <Popover.Arrow className="fill-border" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
