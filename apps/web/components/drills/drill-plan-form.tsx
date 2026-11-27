"use client";

/**
 * A4.7: the plan before the first order (the A5 journal's fields): planned
 * entry, stop and size, long. The ticket stays hidden until a plan is saved;
 * the plan can change until the first fill, then it is locked.
 */

import { useActionState, useId, useState } from "react";

import { type DrillActionState, savePlanAction } from "@/app/(product)/(authed)/drills/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type DrillPlan, planRisk } from "@/lib/drills";
import { formatCurrency } from "@/lib/portfolio-view-model";

export function DrillPlanForm({
  drillId,
  plan,
  currentClose,
  cash,
  currency,
  readOnly,
}: {
  drillId: number;
  plan: DrillPlan | null;
  currentClose: string;
  cash: string;
  currency: string;
  readOnly: boolean;
}) {
  const id = useId();
  const close = Number(currentClose);
  const [entry, setEntry] = useState(
    plan?.planned_entry ? String(Number(plan.planned_entry)) : String(close),
  );
  const [stop, setStop] = useState(
    plan?.planned_stop
      ? String(Number(plan.planned_stop))
      : String(Math.round(close * 0.95 * 100) / 100),
  );
  const [size, setSize] = useState(plan?.planned_size ? String(Number(plan.planned_size)) : "");
  const [state, action, pending] = useActionState<DrillActionState, FormData>(savePlanAction, {});
  const risk = planRisk(Number(entry), Number(stop), Number(size));
  const money = (v: string | number) => formatCurrency(v, currency);

  if (plan?.locked || readOnly) {
    if (!plan) return null;
    return (
      <section
        aria-labelledby={`${id}-t`}
        className="space-y-2"
        data-testid="drill-plan"
        data-locked="true"
      >
        <h2 id={`${id}-t`} className="text-sm font-semibold">
          Your plan {plan.locked ? "(locked at the first fill)" : ""}
        </h2>
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <Item label="Entry" value={money(plan.planned_entry)} />
          <Item label="Stop" value={money(plan.planned_stop)} />
          <Item label="Size" value={`${Number(plan.planned_size)} shares`} />
          <Item label="Planned risk" value={money(plan.planned_risk)} />
        </dl>
        {plan.note ? <p className="text-sm text-text-secondary">{plan.note}</p> : null}
      </section>
    );
  }

  return (
    <form
      action={action}
      className="space-y-4"
      data-testid="drill-plan"
      aria-labelledby={`${id}-t`}
    >
      <div>
        <h2 id={`${id}-t`} className="text-sm font-semibold">
          {plan
            ? "Your plan (editable until the first fill)"
            : "Plan the trade before the first order"}
        </h2>
        <p className="mt-1 text-xs leading-5 text-text-tertiary">
          The drill is scored on whether you follow this plan: entry within 2%, the stop honoured,
          size within the plan. Profit is shown, but it is not the score.
        </p>
      </div>
      <input type="hidden" name="drill_id" value={drillId} />
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-entry`}>Planned entry ({currency})</Label>
          <Input
            id={`${id}-entry`}
            name="planned_entry"
            type="number"
            step="any"
            min="0"
            required
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            data-testid="plan-entry"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-stop`}>Stop ({currency})</Label>
          <Input
            id={`${id}-stop`}
            name="planned_stop"
            type="number"
            step="any"
            min="0"
            required
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            data-testid="plan-stop"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-size`}>Size (shares)</Label>
          <Input
            id={`${id}-size`}
            name="planned_size"
            type="number"
            step="any"
            min="0"
            required
            value={size}
            onChange={(e) => setSize(e.target.value)}
            data-testid="plan-size"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${id}-note`}>Why (optional)</Label>
        <textarea
          id={`${id}-note`}
          name="note"
          maxLength={2000}
          rows={2}
          className="w-full rounded-md border border-border-muted bg-background px-2 py-1.5 text-sm"
        />
      </div>
      <p className="text-xs text-text-tertiary" data-testid="plan-risk">
        {risk === null
          ? !(Number(size) > 0)
            ? "Enter a size in shares to see the planned risk."
            : "The stop must be below the entry (long only)."
          : `Planned risk ${money(risk)} (${((risk / Number(cash)) * 100).toFixed(2)}% of ${money(cash)} cash).`}
      </p>
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : state.ok ? (
        <output className="block text-sm text-positive">Plan saved. The ticket is open.</output>
      ) : null}
      <Button
        type="submit"
        disabled={pending || risk === null}
        className="w-full"
        data-testid="plan-save"
      >
        {pending ? "Saving…" : plan ? "Update plan" : "Save plan"}
      </Button>
    </form>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-text-tertiary">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}
