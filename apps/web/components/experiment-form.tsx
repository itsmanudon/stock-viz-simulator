"use client";

import Link from "next/link";
import { useActionState } from "react";

import {
  type ExperimentFormState,
  createExperimentAction,
} from "@/app/(product)/backtest/experiments/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ExperimentForm() {
  const [state, action, pending] = useActionState<ExperimentFormState, FormData>(
    createExperimentAction,
    {},
  );
  return (
    <form action={action} className="space-y-3" data-testid="experiment-form">
      <div className="space-y-1">
        <Label htmlFor="exp-name">Name</Label>
        <Input id="exp-name" name="name" required maxLength={120} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="exp-hypothesis">Hypothesis, written before you run anything</Label>
        <textarea
          id="exp-hypothesis"
          name="hypothesis"
          rows={3}
          className="w-full rounded-md border border-border-muted bg-background px-3 py-2 text-sm"
          placeholder="RSI(2) pullbacks in an uptrend beat buy-and-hold after costs on US large caps."
        />
      </div>
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : null}
      {state.id ? (
        <p className="text-sm">
          Saved.{" "}
          <Link href={`/backtest?experiment=${state.id}`} className="underline">
            Run backtests into it
          </Link>
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Create experiment"}
      </Button>
    </form>
  );
}
