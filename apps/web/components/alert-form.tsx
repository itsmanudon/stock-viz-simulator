"use client";

import { Bell } from "lucide-react";
import { useActionState, useState } from "react";

import { type CreateAlertState, createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  ticker: string;
};

export function AlertForm({ ticker }: Props) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<CreateAlertState, FormData>(
    createAlertAction,
    {},
  );
  const [direction, setDirection] = useState<"above" | "below">("above");

  if (!open) {
    return (
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Bell className="h-4 w-4" aria-hidden />
        <span className="ml-1.5">Set alert</span>
      </Button>
    );
  }

  return (
    <form action={action} className="flex flex-wrap items-end gap-2 rounded-md border bg-card p-3">
      <input type="hidden" name="ticker" value={ticker} />
      <div className="flex flex-col gap-1">
        <Label htmlFor="alert-direction" className="text-xs">
          When price is
        </Label>
        <select
          id="alert-direction"
          name="direction"
          value={direction}
          onChange={(e) => setDirection(e.target.value as "above" | "below")}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          <option value="above">at or above</option>
          <option value="below">at or below</option>
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="alert-target" className="text-xs">
          Target price
        </Label>
        <Input
          id="alert-target"
          name="target_price"
          type="number"
          min="0.01"
          step="0.01"
          required
          className="h-9 w-32"
        />
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {state.error ? (
        <p className="w-full text-xs text-red-500" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.createdId ? <p className="w-full text-xs text-green-500">Alert set.</p> : null}
    </form>
  );
}
