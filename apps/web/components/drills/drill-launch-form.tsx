"use client";

/**
 * A4.7: "Drill this setup". A rule (a setup or inline text), a universe, a
 * date range, K drills, N bars of lead-in and M after, an optional seed and
 * the anonymisation switch (on by default). The entry points (screener rule
 * panel, /setups, a strategy backtest, the event study) link here with the
 * rule and universe filled in (`drillLaunchHref`).
 */

import { useId, useState, useTransition } from "react";

import { createDeckAction } from "@/app/(product)/(authed)/drills/actions";
import { RuleFieldEditor, type StrategySetupOption } from "@/components/rule-strategy/rule-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DRILL_FOLLOW,
  DRILL_K,
  DRILL_LEAD,
  type LaunchForm,
  type LaunchUniverse,
  buildDeckRequest,
  launchProblem,
} from "@/lib/drills";
import type { RuleField } from "@/lib/rule-strategy";

export type DrillLaunchInitial = {
  rule: string;
  setupVersionId: number | null;
  universe: LaunchUniverse;
  market: "US" | "IN";
  tickers: string;
  watchlistId: string;
  from: string;
  to: string;
};

export function DrillLaunchForm({
  initial,
  setups,
  watchlists,
}: {
  initial: DrillLaunchInitial;
  setups: StrategySetupOption[];
  watchlists: Array<{ id: number; name: string; count: number }>;
}) {
  const id = useId();
  const [rule, setRule] = useState<RuleField>({
    text:
      initial.rule ||
      (initial.setupVersionId
        ? (setups.find((s) => s.versionId === initial.setupVersionId)?.rule ?? "")
        : ""),
    versionId: initial.setupVersionId,
  });
  const [ruleValid, setRuleValid] = useState(true);
  const [form, setForm] = useState<Omit<LaunchForm, "rule" | "setupVersionId">>({
    name: "",
    universe: initial.universe,
    market: initial.market,
    tickers: initial.tickers,
    watchlistId: initial.watchlistId,
    from: initial.from,
    to: initial.to,
    k: String(DRILL_K.default),
    lead: String(DRILL_LEAD.default),
    follow: String(DRILL_FOLLOW.default),
    seed: "",
    anonymised: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const full: LaunchForm = {
    ...form,
    rule: rule.text,
    setupVersionId: rule.versionId ? String(rule.versionId) : "",
  };
  const problem = !ruleValid ? "The rule does not compile yet." : launchProblem(full);
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setError(null);
    start(async () => {
      const result = await createDeckAction(buildDeckRequest(full));
      if (result?.error) setError(result.error);
    });
  }

  return (
    <form
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(e);
      }}
      className="space-y-6 border-y border-border-muted py-5 sm:border-x sm:px-6"
      data-testid="drill-launch"
      aria-labelledby={`${id}-title`}
    >
      <div>
        <h2 id={`${id}-title`} className="text-base font-semibold">
          Drill this setup
        </h2>
        <p className="mt-1 text-sm text-text-secondary">
          Each drill is a replay that opens on a real day the rule turned true, with the bars before
          it visible. You plan, trade and step forward; the score is whether you followed your plan,
          not the profit.
        </p>
      </div>

      <RuleFieldEditor
        label="Rule"
        hint="A condition in the Rule DSL; a trigger is a session where it turns true after being false."
        value={rule}
        onChange={setRule}
        onValidity={setRuleValid}
        setups={setups}
      />

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">Universe</legend>
        <div className="flex flex-wrap gap-4 text-sm">
          {(
            [
              ["market", "A market"],
              ["tickers", "Ticker list"],
              ["watchlist", "Watchlist"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="inline-flex items-center gap-2">
              <input
                type="radio"
                name={`${id}-universe`}
                value={value}
                checked={form.universe === value}
                onChange={() => set("universe", value)}
              />
              {label}
            </label>
          ))}
        </div>
        {form.universe === "market" ? (
          <select
            aria-label="Market"
            value={form.market}
            onChange={(e) => set("market", e.target.value as "US" | "IN")}
            className="h-9 rounded-md border border-border-muted bg-background px-2 text-sm"
            data-testid="drill-market"
          >
            <option value="US">US listings</option>
            <option value="IN">Indian listings (NSE, BSE)</option>
          </select>
        ) : form.universe === "tickers" ? (
          <Input
            aria-label="Tickers"
            placeholder="AAPL, MSFT, RELIANCE.NS"
            value={form.tickers}
            onChange={(e) => set("tickers", e.target.value)}
          />
        ) : watchlists.length ? (
          <select
            aria-label="Watchlist"
            value={form.watchlistId}
            onChange={(e) => set("watchlistId", e.target.value)}
            className="h-9 rounded-md border border-border-muted bg-background px-2 text-sm"
          >
            <option value="">Pick a watchlist…</option>
            {watchlists.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} ({w.count})
              </option>
            ))}
          </select>
        ) : (
          <p className="text-sm text-text-secondary">You have no watchlists yet.</p>
        )}
        {form.market === "IN" || form.tickers.toUpperCase().match(/\.(NS|BO)\b/) ? (
          <p className="text-xs text-text-tertiary" data-testid="drill-lag-note">
            NSE/BSE triggers whose drill would end within 30 days of today are skipped and counted.
          </p>
        ) : null}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field id={`${id}-from`} label="From (optional)">
          <Input
            id={`${id}-from`}
            type="date"
            value={form.from}
            onChange={(e) => set("from", e.target.value)}
          />
        </Field>
        <Field id={`${id}-to`} label="To (optional)">
          <Input
            id={`${id}-to`}
            type="date"
            value={form.to}
            onChange={(e) => set("to", e.target.value)}
          />
        </Field>
        <Field id={`${id}-k`} label={`Drills (K, ${DRILL_K.min}-${DRILL_K.max})`}>
          <Input
            id={`${id}-k`}
            type="number"
            min={DRILL_K.min}
            max={DRILL_K.max}
            value={form.k}
            onChange={(e) => set("k", e.target.value)}
            data-testid="drill-k"
          />
        </Field>
        <Field id={`${id}-seed`} label="Seed (optional)">
          <Input
            id={`${id}-seed`}
            type="number"
            min={0}
            placeholder="random"
            value={form.seed}
            onChange={(e) => set("seed", e.target.value)}
          />
        </Field>
        <Field id={`${id}-lead`} label="Bars before the trigger (N)">
          <Input
            id={`${id}-lead`}
            type="number"
            min={DRILL_LEAD.min}
            max={DRILL_LEAD.max}
            value={form.lead}
            onChange={(e) => set("lead", e.target.value)}
          />
        </Field>
        <Field id={`${id}-follow`} label="Bars after the trigger (M)">
          <Input
            id={`${id}-follow`}
            type="number"
            min={DRILL_FOLLOW.min}
            max={DRILL_FOLLOW.max}
            value={form.follow}
            onChange={(e) => set("follow", e.target.value)}
          />
        </Field>
        <Field id={`${id}-name`} label="Deck name (optional)">
          <Input
            id={`${id}-name`}
            maxLength={120}
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
      </div>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.anonymised}
          onChange={(e) => set("anonymised", e.target.checked)}
          data-testid="drill-anonymised"
        />
        <span>
          Anonymise the drills (recommended)
          <span className="block text-xs text-text-tertiary">
            The symbol shows as Stock A, B, C…; company, sector and headlines are hidden; dates move
            by a whole number of weeks, so weekdays stay real. Everything is revealed when you
            finish a drill.
          </span>
        </span>
      </label>

      {error ? (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      ) : problem ? (
        <p className="text-sm text-text-tertiary">{problem}</p>
      ) : null}
      <Button type="submit" disabled={pending || Boolean(problem)} data-testid="drill-create">
        {pending ? "Finding triggers…" : "Create deck"}
      </Button>
    </form>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}
