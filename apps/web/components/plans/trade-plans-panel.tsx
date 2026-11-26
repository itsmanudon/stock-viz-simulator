"use client";

/**
 * Trade plans on the Portfolio Journal tab (A5.4, M10.3): the selected
 * book's plans, newest first, each with its status, the lock badge ("Locked"
 * at the first fill, or "Written after entry"), entry, stop, target, R:R and
 * risk. A row opens to its thesis and notes and a small editor: notes and
 * tags always, the plan's prices only before any fill (the API refuses the
 * rest with 409). "Plan an open position" writes a plan for a holding that
 * has none; its fills came first, so it is labelled written after entry.
 */

import Link from "next/link";
import { useActionState, useId, useMemo, useState } from "react";

import {
  type PlanActionState,
  planOpenPositionAction,
  updatePlanAction,
} from "@/app/(product)/(authed)/portfolio/plan-actions";
import { formatMoney } from "@/components/order-review";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatUtcDateTime } from "@/lib/api-time";
import { PLAN_STATUS_LABEL, type TradePlan, planBadge } from "@/lib/plans";

export type PlanPosition = {
  ticker: string;
  quantity: string;
  avgCost: string;
  currency: string;
};

type Filter = "all" | TradePlan["status"];
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "active", label: "Active" },
  { value: "closed", label: "Closed" },
  { value: "cancelled", label: "Cancelled" },
];

const BADGE_CLASS: Record<ReturnType<typeof planBadge>["tone"], string> = {
  locked: "border-brand/40 bg-brand/10 text-foreground",
  after: "border-warning/40 bg-warning-soft text-warning-soft-foreground",
  open: "border-border-muted text-text-secondary",
  done: "border-border-muted text-text-tertiary",
};

function money(value: string | null, currency: string): string {
  return value === null ? "—" : formatMoney(Number(value), currency);
}

export function TradePlansPanel({
  plans,
  bookId,
  writable,
  positions,
}: {
  plans: TradePlan[] | null;
  bookId: number | null;
  writable: boolean;
  positions: PlanPosition[];
}) {
  const id = useId();
  const [filter, setFilter] = useState<Filter>("all");
  const shown = useMemo(
    () => (plans ?? []).filter((p) => filter === "all" || p.status === filter),
    [plans, filter],
  );
  const planned = new Set((plans ?? []).filter((p) => p.status === "active").map((p) => p.ticker));
  const unplanned = positions.filter((p) => !planned.has(p.ticker));

  return (
    <section aria-labelledby={`${id}-title`} className="space-y-4" data-testid="trade-plans">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={`${id}-title`} className="text-base font-semibold tracking-tight">
            Trade plans
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary">
            Written before the order and locked at its first fill. A plan written after the entry is
            labelled so and never counts as locked.
          </p>
        </div>
        {plans?.length ? (
          <fieldset className="flex flex-wrap gap-1.5" aria-label="Filter plans by status">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                aria-pressed={filter === f.value}
                onClick={() => setFilter(f.value)}
                className={`h-7 rounded-full border px-3 text-xs ${
                  filter === f.value
                    ? "border-brand/50 bg-brand/10 text-foreground"
                    : "border-border-muted text-muted-foreground hover:bg-surface-hover"
                }`}
              >
                {f.label}
              </button>
            ))}
          </fieldset>
        ) : null}
      </div>

      {plans === null ? (
        <p className="text-sm text-muted-foreground">Plans are unavailable right now.</p>
      ) : plans.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-muted px-4 py-5 text-sm text-text-secondary">
          No plans in this book yet. Tick “Plan this trade” on an{" "}
          <Link
            href={bookId ? `/trade?book=${bookId}` : "/trade"}
            className="underline underline-offset-2"
          >
            order ticket
          </Link>{" "}
          to write one before you buy.
        </p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">No {filter} plans.</p>
      ) : (
        <ul className="divide-y divide-border-muted rounded-md border border-border-muted">
          {shown.map((plan) => (
            <PlanRow key={plan.id} plan={plan} writable={writable} />
          ))}
        </ul>
      )}

      {writable && unplanned.length ? (
        <PlanOpenPosition positions={unplanned} bookId={bookId} />
      ) : null}
    </section>
  );
}

function PlanRow({ plan, writable }: { plan: TradePlan; writable: boolean }) {
  const badge = planBadge(plan);
  const cur = plan.currency;
  const [state, action, pending] = useActionState<PlanActionState, FormData>(updatePlanAction, {});
  const editable = writable && !plan.frozen && plan.status === "open";
  const fid = useId();

  return (
    <li data-testid="plan-row" data-status={plan.status} data-badge={badge.tone}>
      <details className="group">
        <summary className="grid cursor-pointer list-none grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-4 py-3 hover:bg-surface-hover sm:grid-cols-[minmax(7rem,1fr)_repeat(4,minmax(0,auto))_auto] sm:items-center">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="ticker text-sm font-semibold">{plan.ticker ?? "—"}</span>
            <span
              className={`rounded-full border px-2 py-0.5 text-2xs font-medium ${BADGE_CLASS[badge.tone]}`}
              data-testid="plan-badge"
            >
              {badge.label}
            </span>
            <span className="text-2xs text-text-tertiary">{PLAN_STATUS_LABEL[plan.status]}</span>
          </span>
          <Figure
            label="Entry"
            value={money(plan.planned_entry, cur)}
            className="hidden sm:block"
          />
          <Figure label="Stop" value={money(plan.planned_stop, cur)} className="hidden sm:block" />
          <Figure
            label="Target"
            value={money(plan.planned_target, cur)}
            className="hidden sm:block"
          />
          <Figure label="Risk" value={money(plan.planned_risk, cur)} className="hidden sm:block" />
          <Figure
            label="R:R"
            value={plan.reward_risk ? `${Number(plan.reward_risk).toFixed(2)}` : "—"}
          />
          <p className="col-span-2 font-mono text-2xs tabular-nums text-text-secondary sm:hidden">
            Entry {money(plan.planned_entry, cur)} · stop {money(plan.planned_stop, cur)} · target{" "}
            {money(plan.planned_target, cur)} · risk {money(plan.planned_risk, cur)}
          </p>
        </summary>

        <div className="space-y-3 border-t border-border-muted bg-surface-secondary/30 px-4 py-3 text-sm">
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <Meta
              label="Planned size"
              value={plan.planned_size ? `${Number(plan.planned_size)} shares` : "—"}
            />
            <Meta label="Setup" value={plan.setup_label ?? "None"} />
            <Meta label="Written" value={formatUtcDateTime(plan.created_at)} />
            <Meta
              label={plan.written_after_entry ? "First fill (before the plan)" : "Locked at"}
              value={
                plan.locked_at || plan.first_fill_at
                  ? formatUtcDateTime(plan.locked_at ?? plan.first_fill_at)
                  : "Not filled yet"
              }
            />
            <Meta label="Fills linked" value={String(plan.fills)} />
            {plan.thesis_title ? <Meta label="Thesis" value={plan.thesis_title} /> : null}
          </dl>
          {plan.thesis_text ? <p className="text-text-secondary">{plan.thesis_text}</p> : null}
          {plan.why ? <p className="text-text-secondary">Why now: {plan.why}</p> : null}
          {plan.written_after_entry ? (
            <p className="text-xs text-warning">
              Written after entry: the first fill came before this plan, so it records intent after
              the fact and is left out of plan-adherence figures.
            </p>
          ) : null}

          {writable ? (
            <form action={action} className="space-y-3">
              <input type="hidden" name="plan_id" value={plan.id} />
              {editable ? (
                <>
                  <input type="hidden" name="editable" value="1" />
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Field id={`${fid}-e`} name="entry" label="Entry" value={plan.planned_entry} />
                    <Field id={`${fid}-s`} name="stop" label="Stop" value={plan.planned_stop} />
                    <Field
                      id={`${fid}-t`}
                      name="target"
                      label="Target"
                      value={plan.planned_target}
                    />
                    <Field id={`${fid}-z`} name="size" label="Size" value={plan.planned_size} />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor={`${fid}-why`} className="text-xs">
                      Why now
                    </Label>
                    <Input id={`${fid}-why`} name="why" defaultValue={plan.why ?? ""} />
                  </div>
                </>
              ) : (
                <p className="text-xs text-text-tertiary">
                  {plan.frozen
                    ? "Entry, stop, target, size and the reasons are frozen. Notes and tags stay editable."
                    : `This plan is ${plan.status}.`}
                </p>
              )}
              <div className="grid gap-2 sm:grid-cols-[2fr_1fr]">
                <div className="space-y-1">
                  <Label htmlFor={`${fid}-notes`} className="text-xs">
                    Notes
                  </Label>
                  <textarea
                    id={`${fid}-notes`}
                    name="notes"
                    rows={2}
                    maxLength={8000}
                    defaultValue={plan.notes ?? ""}
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`${fid}-tags`} className="text-xs">
                    Tags
                  </Label>
                  <Input id={`${fid}-tags`} name="tags" defaultValue={plan.tags.join(", ")} />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="sm" disabled={pending}>
                  Save
                </Button>
                {plan.status === "open" ? (
                  <Button
                    type="submit"
                    size="sm"
                    variant="outline"
                    name="intent"
                    value="cancel"
                    disabled={pending}
                  >
                    Cancel plan
                  </Button>
                ) : null}
                {plan.status === "active" ? (
                  <Button
                    type="submit"
                    size="sm"
                    variant="outline"
                    name="intent"
                    value="close"
                    disabled={pending}
                  >
                    Close plan
                  </Button>
                ) : null}
                {state.error ? (
                  <p className="text-xs text-negative" role="alert">
                    {state.error}
                  </p>
                ) : state.ok ? (
                  <output className="text-xs text-positive">{state.ok}</output>
                ) : null}
              </div>
            </form>
          ) : null}
        </div>
      </details>
    </li>
  );
}

function Figure({
  label,
  value,
  className = "",
}: { label: string; value: string; className?: string }) {
  return (
    <span className={`text-right ${className}`}>
      <span className="block text-2xs text-text-tertiary">{label}</span>
      <span className="font-mono text-xs tabular-nums">{value}</span>
    </span>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 sm:block">
      <dt className="text-text-tertiary">{label}</dt>
      <dd className="text-right sm:text-left">{value}</dd>
    </div>
  );
}

function Field({
  id,
  name,
  label,
  value,
}: { id: string; name: string; label: string; value: string | null }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <Input
        id={id}
        name={name}
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        defaultValue={value === null ? "" : String(Number(value))}
        className="font-mono tabular-nums"
      />
    </div>
  );
}

function PlanOpenPosition({
  positions,
  bookId,
}: { positions: PlanPosition[]; bookId: number | null }) {
  const id = useId();
  const [ticker, setTicker] = useState(positions[0]?.ticker ?? "");
  const chosen = positions.find((p) => p.ticker === ticker) ?? positions[0];
  const [state, action, pending] = useActionState<PlanActionState, FormData>(
    planOpenPositionAction,
    {},
  );
  return (
    <details className="rounded-md border border-border-muted" data-testid="plan-open-position">
      <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground">
        Plan an open position
      </summary>
      <form action={action} className="space-y-3 border-t border-border-muted px-4 py-3">
        <p className="text-xs text-text-tertiary">
          For a holding you bought without a plan. It is labelled “written after entry” and never
          shown as locked.
        </p>
        {bookId ? <input type="hidden" name="book_id" value={bookId} /> : null}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <div className="col-span-2 space-y-1 sm:col-span-1">
            <Label htmlFor={`${id}-ticker`} className="text-xs">
              Position
            </Label>
            <select
              id={`${id}-ticker`}
              name="ticker"
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
            >
              {positions.map((p) => (
                <option key={p.ticker} value={p.ticker}>
                  {p.ticker} ({Number(p.quantity)})
                </option>
              ))}
            </select>
          </div>
          <Field
            key={`e-${chosen?.ticker}`}
            id={`${id}-entry`}
            name="entry"
            label="Entry"
            value={chosen?.avgCost ?? null}
          />
          <Field id={`${id}-stop`} name="stop" label="Stop" value={null} />
          <Field id={`${id}-target`} name="target" label="Target" value={null} />
          <Field
            key={`z-${chosen?.ticker}`}
            id={`${id}-size`}
            name="size"
            label="Size"
            value={chosen?.quantity ?? null}
          />
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor={`${id}-why`} className="text-xs">
              Why
            </Label>
            <Input id={`${id}-why`} name="why" />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${id}-tags`} className="text-xs">
              Tags
            </Label>
            <Input id={`${id}-tags`} name="tags" />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="sm" disabled={pending}>
            Save plan
          </Button>
          {state.error ? (
            <p className="text-xs text-negative" role="alert">
              {state.error}
            </p>
          ) : state.ok ? (
            <output className="text-xs text-positive">{state.ok}</output>
          ) : null}
        </div>
      </form>
    </details>
  );
}
