"use client";

/**
 * "Plan this trade" (A5.4, M10.3): the optional plan on both paper tickets.
 *
 * `TicketPlanSection` edits the plan while the ticket is a draft;
 * `PlanReview` shows it in the order review with its risk and R:R and posts
 * it as hidden fields (the review's button submits exactly what is shown).
 * The server action turns those fields into the API's `plan` and the order
 * creates it and links its fill, which locks it (lib/plans.ts).
 */

import { useId } from "react";

import { formatMoney } from "@/components/order-review";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type PlanFormState,
  type PlanSetupOption,
  type PlanThesisOption,
  planFigures,
  planFormFields,
  splitTags,
} from "@/lib/plans";

export type TicketPlanOptions = {
  setups: PlanSetupOption[];
  theses: PlanThesisOption[];
};

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm";

function rr(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(2)} : 1`;
}

export function TicketPlanSection({
  form,
  onChange,
  ticker,
  currency,
  referencePrice,
  quantity,
  options,
}: {
  form: PlanFormState;
  onChange: (next: PlanFormState) => void;
  ticker: string;
  currency: string;
  referencePrice: string | null;
  quantity: string;
  options: TicketPlanOptions | null;
}) {
  const id = useId();
  const figures = planFigures(form);
  const theses = (options?.theses ?? []).filter((t) => t.ticker === ticker);
  const set = (patch: Partial<PlanFormState>) => onChange({ ...form, ...patch });

  function toggle(enabled: boolean) {
    // Start from the order: its price and quantity, unless already typed.
    onChange({
      ...form,
      enabled,
      entry: form.entry || (referencePrice ? String(Number(referencePrice)) : ""),
      size: form.size || quantity,
    });
  }

  return (
    <div
      className="rounded-md border border-border-muted bg-surface-secondary/40"
      data-testid="ticket-plan"
    >
      <label className="flex cursor-pointer items-start gap-3 px-3 py-2.5">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) => toggle(event.target.checked)}
          className="mt-0.5 size-4 accent-[var(--brand)]"
        />
        <span>
          <span className="block text-sm font-medium">Plan this trade</span>
          <span className="block text-xs leading-5 text-text-tertiary">
            Entry, stop and size, written before the order. It locks when the order fills.
          </span>
        </span>
      </label>

      {form.enabled ? (
        <div className="space-y-3 border-t border-border-muted px-3 py-3">
          <div className="grid grid-cols-2 gap-2">
            <PlanNumber
              id={`${id}-entry`}
              label="Planned entry"
              value={form.entry}
              onChange={(v) => set({ entry: v })}
              currency={currency}
            />
            <PlanNumber
              id={`${id}-stop`}
              label="Stop"
              value={form.stop}
              onChange={(v) => set({ stop: v })}
              currency={currency}
            />
            <PlanNumber
              id={`${id}-target`}
              label="Target (optional)"
              value={form.target}
              onChange={(v) => set({ target: v })}
              currency={currency}
            />
            <PlanNumber
              id={`${id}-size`}
              label="Size (shares)"
              value={form.size}
              onChange={(v) => set({ size: v })}
            />
          </div>

          <dl className="grid grid-cols-3 gap-2 text-xs" data-testid="ticket-plan-figures">
            <div>
              <dt className="text-text-tertiary">Risk</dt>
              <dd className="font-mono tabular-nums">
                {figures.risk === null ? "—" : formatMoney(figures.risk, currency)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Per share</dt>
              <dd className="font-mono tabular-nums">
                {figures.riskPerShare === null ? "—" : formatMoney(figures.riskPerShare, currency)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Reward : risk</dt>
              <dd className="font-mono tabular-nums">{rr(figures.rewardRisk)}</dd>
            </div>
          </dl>
          {figures.problem ? (
            <output className="block text-xs text-warning">{figures.problem}</output>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor={`${id}-setup`}>Setup</Label>
            <select
              id={`${id}-setup`}
              value={form.setupVersionId}
              onChange={(event) => set({ setupVersionId: event.target.value })}
              className={selectClass}
            >
              <option value="">No setup</option>
              {(options?.setups ?? []).map((s) => (
                <option key={s.versionId} value={s.versionId}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {theses.length ? (
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-thesis`}>Thesis on {ticker}</Label>
              <select
                id={`${id}-thesis`}
                value={form.thesisId}
                onChange={(event) => set({ thesisId: event.target.value })}
                className={selectClass}
              >
                <option value="">None</option>
                {theses.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor={`${id}-thesis-text`}>Thesis (your words)</Label>
            <textarea
              id={`${id}-thesis-text`}
              value={form.thesisText}
              maxLength={4000}
              rows={2}
              onChange={(event) => set({ thesisText: event.target.value })}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div className="grid gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-why`}>Why now</Label>
              <Input
                id={`${id}-why`}
                value={form.why}
                maxLength={2000}
                onChange={(event) => set({ why: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-tags`}>Tags</Label>
              <Input
                id={`${id}-tags`}
                value={form.tags}
                placeholder="breakout, earnings"
                onChange={(event) => set({ tags: event.target.value })}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PlanNumber({
  id,
  label,
  value,
  onChange,
  currency,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  currency?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <div className="relative">
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={`font-mono tabular-nums ${currency ? "pr-11" : ""}`}
        />
        {currency ? (
          <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-2xs text-text-tertiary">
            {currency}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** The plan in the order review: what it risks, its R:R, and the lock. */
export function PlanReview({
  form,
  currency,
  quantity,
  options,
}: {
  form: PlanFormState;
  currency: string;
  quantity: string;
  options: TicketPlanOptions | null;
}) {
  if (!form.enabled) return null;
  const figures = planFigures(form);
  const fields = planFormFields(form);
  const setup = options?.setups.find((s) => String(s.versionId) === form.setupVersionId);
  const thesis = options?.theses.find((t) => String(t.id) === form.thesisId);
  const tags = splitTags(form.tags);
  const sizeDiffers = Number(form.size) > 0 && Number(quantity) !== Number(form.size);
  const rows: { label: string; value: string }[] = [
    { label: "Entry", value: formatMoney(Number(form.entry), currency) },
    { label: "Stop", value: formatMoney(Number(form.stop), currency) },
    {
      label: "Target",
      value: form.target ? formatMoney(Number(form.target), currency) : "None set",
    },
    { label: "Planned size", value: `${form.size} shares` },
    {
      label: "Risk if stopped",
      value: figures.risk === null ? "—" : formatMoney(figures.risk, currency),
    },
    { label: "Reward : risk", value: rr(figures.rewardRisk) },
  ];
  if (setup) rows.push({ label: "Setup", value: setup.label });
  if (thesis) rows.push({ label: "Thesis", value: thesis.title });

  return (
    <section
      aria-label="Your plan"
      className="rounded-xl border border-brand/30 bg-brand/5 text-xs"
      data-testid="review-plan"
    >
      {Object.entries(fields).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <p className="px-3 pt-2.5 text-xs font-semibold text-brand">Your plan</p>
      <dl className="divide-y divide-border-muted">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start justify-between gap-4 px-3 py-2">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="text-right font-mono tabular-nums">{row.value}</dd>
          </div>
        ))}
      </dl>
      {form.thesisText || form.why || tags.length ? (
        <div className="space-y-1 border-t border-border-muted px-3 py-2 text-text-secondary">
          {form.thesisText ? <p>{form.thesisText}</p> : null}
          {form.why ? <p>Why now: {form.why}</p> : null}
          {tags.length ? <p className="text-text-tertiary">Tags: {tags.join(", ")}</p> : null}
        </div>
      ) : null}
      <p className="border-t border-border-muted px-3 py-2 text-2xs leading-4 text-text-tertiary">
        {figures.problem
          ? `Not a valid plan yet: ${figures.problem.toLowerCase()}.`
          : sizeDiffers
            ? `This order is ${quantity} of the ${form.size} planned shares. The plan locks at this fill; later fills add to it.`
            : "The plan locks when this order fills. After that only its notes and tags can change."}
      </p>
    </section>
  );
}
