"use client";

import { useActionState } from "react";

import { type ThesisFormState, createThesisAction } from "@/app/(product)/(authed)/theses/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ThesisForm() {
  const [state, action, pending] = useActionState<ThesisFormState, FormData>(
    createThesisAction,
    {},
  );
  return (
    <form action={action} className="space-y-3" data-testid="thesis-form">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="thesis-ticker">Ticker</Label>
          <Input id="thesis-ticker" name="ticker" placeholder="AAPL" required />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="thesis-title">Title</Label>
          <Input id="thesis-title" name="title" required maxLength={160} />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="thesis-body">Thesis</Label>
        <textarea
          id="thesis-body"
          name="body"
          required
          rows={4}
          className="w-full rounded-md border border-border-muted bg-background px-3 py-2 text-sm"
          placeholder="Why this works, the drivers, what you are watching."
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="thesis-kill">Kill rule (Rule DSL, optional)</Label>
        <Input id="thesis-kill" name="kill_rule" placeholder="close < sma(close, 200)" />
        <p className="text-xs text-text-tertiary">
          Judged each night on the latest daily bar. When it turns true you are notified once; the
          thesis stays as it is until you close it.
        </p>
      </div>
      {state.error ? (
        <p className="text-sm text-negative" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.saved ? <p className="text-sm text-positive">Thesis saved.</p> : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Save thesis"}
      </Button>
    </form>
  );
}
