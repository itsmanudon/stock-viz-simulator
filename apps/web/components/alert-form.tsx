"use client";

import { Bell } from "lucide-react";
import { Popover } from "radix-ui";
import { useActionState, useId, useState } from "react";

import { type CreateAlertState, createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AlertForm({ ticker }: { ticker: string }) {
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<CreateAlertState, FormData>(
    createAlertAction,
    {},
  );
  const [direction, setDirection] = useState<"above" | "below">("above");

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
              Notify me when {ticker} reaches a target.
            </p>
          </div>
          <form action={action} className="space-y-3">
            <input type="hidden" name="ticker" value={ticker} />
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-direction`} className="text-xs">
                When price is
              </Label>
              <select
                id={`${fieldId}-direction`}
                name="direction"
                value={direction}
                onChange={(event) => setDirection(event.target.value as "above" | "below")}
                className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
            </div>
            {state.error ? (
              <p className="text-xs text-negative" role="alert">
                {state.error}
              </p>
            ) : null}
            {state.createdId ? <p className="text-xs text-positive">Alert set.</p> : null}
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" size="sm" disabled={pending}>
                {pending ? "Saving…" : "Save alert"}
              </Button>
            </div>
          </form>
          <Popover.Arrow className="fill-border" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
