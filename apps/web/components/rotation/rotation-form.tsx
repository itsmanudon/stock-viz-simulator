"use client";

/**
 * A4.4 (M7.1, rotation): the Rotation mode of /backtest. Hold the top N of a
 * universe by a numeric Rule DSL ranking (checked as a number as the user
 * types), rebalanced weekly or monthly on the venue calendar, with an
 * optional cash filter on the market index. The run goes through
 * `runRotationAction` (authed when signed in). Ctrl/Cmd+Enter runs it.
 */

import { useCallback, useMemo, useState } from "react";

import {
  type RotationRunState,
  runRotationAction,
} from "@/app/(product)/backtest/rotation-actions";
import { ResearchEmptyState } from "@/components/research-page-header";
import { RotationResults } from "@/components/rotation/rotation-results";
import { RuleFieldEditor, type StrategySetupOption } from "@/components/rule-strategy/rule-field";
import type { StrategyWatchlist } from "@/components/rule-strategy/rule-strategy-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { checkNumber } from "@/lib/api/rules";
import type { BacktestSymbol } from "@/lib/backtest-defaults";
import { BROKERAGE_OPTIONS, FEE_SCHEDULE_OPTIONS } from "@/lib/fees";
import { HOLDOUT_OPTIONS } from "@/lib/report-card";
import {
  type RotationForm as Form,
  type RotationRequest,
  buildRotationRequest,
  initialRotationForm,
  marketTickers,
  rotationProblem,
  rotationRange,
} from "@/lib/rotation";

const SELECT = "flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm";

export function RotationForm({
  symbols,
  setups,
  watchlists,
  signedIn,
  run = runRotationAction,
}: {
  symbols: BacktestSymbol[];
  setups: StrategySetupOption[];
  watchlists: StrategyWatchlist[];
  signedIn: boolean;
  run?: (request: RotationRequest) => Promise<RotationRunState>;
}) {
  const us = useMemo(() => marketTickers(symbols, "US"), [symbols]);
  const india = useMemo(() => marketTickers(symbols, "IN"), [symbols]);
  const lastClose = useMemo(
    () => symbols.find((s) => s.ticker === (us[0] ?? india[0]))?.lastClose,
    [symbols, us, india],
  );
  const [form, setForm] = useState<Form>(() =>
    initialRotationForm(us.length ? us : india, rotationRange(lastClose)),
  );
  const [rankValid, setRankValid] = useState(true);
  const [filterValid, setFilterValid] = useState(true);
  const [pending, setPending] = useState(false);
  const [state, setState] = useState<RotationRunState & { request?: RotationRequest }>({});

  const set = useCallback(
    <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value })),
    [],
  );
  const onRank = useCallback((v: boolean) => setRankValid(v), []);
  const onFilter = useCallback((v: boolean) => setFilterValid(v), []);
  const problem = rotationProblem(form, rankValid && (!form.useCashFilter || filterValid));

  async function submit() {
    if (problem || pending) return;
    const request = buildRotationRequest(form);
    setPending(true);
    try {
      const next = await run(request);
      setState({ ...next, request });
    } catch {
      setState({ error: "The run failed. Try again." });
    } finally {
      setPending(false);
    }
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submit();
    }
  }

  const field = (key: keyof Form, label: string, props: Record<string, string> = {}) => (
    <div className="space-y-1">
      <Label htmlFor={`rot-${key}`} className="text-xs">
        {label}
      </Label>
      <Input
        id={`rot-${key}`}
        type="number"
        value={String(form[key])}
        onChange={(e) => set(key, e.target.value as never)}
        {...props}
      />
    </div>
  );

  return (
    <div className="mt-6 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)] lg:items-start">
      <section
        aria-labelledby="rotation-setup-heading"
        className="border-y border-border-muted sm:border-x"
      >
        <div className="border-b border-border-muted px-4 py-3">
          <h2 id="rotation-setup-heading" className="text-sm font-semibold">
            Rotation
          </h2>
          <p className="mt-1 text-xs leading-5 text-text-tertiary">
            Hold the top N by a ranking. It ranks on the last session of each week or month, from
            values known at that close, and trades on the next session.
          </p>
        </div>
        <form
          className="space-y-5 p-4"
          onKeyDown={onKeyDown}
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          data-testid="rotation-form"
        >
          <RuleFieldEditor
            label="Ranking (a number; higher ranks first)"
            hint="e.g. pct_change(close, 126): the 126-session return."
            value={{ text: form.ranking, versionId: null }}
            onChange={(v) => set("ranking", v.text)}
            onValidity={onRank}
            setups={[]}
            check={checkNumber}
          />

          <div className="grid grid-cols-3 gap-2">
            {field("topN", "Top N", { min: "1", max: "50", step: "1" })}
            <div className="space-y-1">
              <Label htmlFor="rot-schedule" className="text-xs">
                Rebalance
              </Label>
              <select
                id="rot-schedule"
                value={form.schedule}
                onChange={(e) => set("schedule", e.target.value as Form["schedule"])}
                className={SELECT}
              >
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>
            {field("buffer", "Buffer", { min: "0", max: "50", step: "1" })}
          </div>
          <p className="-mt-3 text-2xs text-text-tertiary">
            Buffer: a holding stays while its rank is at most N + buffer.
          </p>
          <div className="space-y-1">
            <Label htmlFor="rot-weighting" className="text-xs">
              Weighting
            </Label>
            <select
              id="rot-weighting"
              value={form.weighting}
              onChange={(e) => set("weighting", e.target.value as Form["weighting"])}
              className={SELECT}
            >
              <option value="equal">Equal: 1/N of equity a name</option>
              <option value="inverse_volatility">Inverse volatility (63 sessions)</option>
            </select>
            <p className="text-2xs text-text-tertiary">
              Names that stay are not resized; only names entering and leaving trade.
            </p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Cash filter</legend>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.useCashFilter}
                onChange={(e) => set("useCashFilter", e.target.checked)}
              />
              Hold cash when the market rule is met
            </label>
            {form.useCashFilter ? (
              <RuleFieldEditor
                label="Cash filter rule"
                hint="Judged on the market index (S&P 500 or NIFTY 50) at each rebalance close."
                value={form.cashFilter}
                onChange={(v) => set("cashFilter", v)}
                onValidity={onFilter}
                setups={setups}
              />
            ) : null}
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Universe</legend>
            <div className="flex flex-wrap gap-3 text-sm" role="radiogroup" aria-label="Universe">
              {(
                [
                  ["list", "Ticker list"],
                  ["watchlist", "Watchlist"],
                ] as const
              ).map(([kind, label]) => (
                <label key={kind} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="rotation-universe"
                    checked={form.universeKind === kind}
                    disabled={kind === "watchlist" && !signedIn}
                    onChange={() => set("universeKind", kind)}
                  />
                  {label}
                </label>
              ))}
            </div>
            {form.universeKind === "list" ? (
              <div className="space-y-1">
                <Label htmlFor="rot-list" className="text-xs">
                  Tickers (2 to 50, one currency)
                </Label>
                <textarea
                  id="rot-list"
                  value={form.tickerList}
                  onChange={(e) => set("tickerList", e.target.value)}
                  rows={3}
                  className="w-full rounded-sm border border-input bg-transparent px-3 py-2 font-mono text-xs leading-5"
                />
                <div className="flex flex-wrap gap-2">
                  {us.length ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => set("tickerList", us.join(", "))}
                    >
                      All US ({us.length})
                    </Button>
                  ) : null}
                  {india.length ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => set("tickerList", india.join(", "))}
                    >
                      All India ({india.length})
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : watchlists.length ? (
              <select
                aria-label="Watchlist"
                value={form.watchlistId}
                onChange={(e) => set("watchlistId", e.target.value)}
                className={SELECT}
              >
                <option value="">Choose a watchlist…</option>
                {watchlists.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} ({w.count})
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-xs text-text-tertiary">You have no watchlists yet.</p>
            )}
            {!signedIn ? (
              <p className="text-xs text-text-tertiary">Sign in to rotate a watchlist.</p>
            ) : null}
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="rot-from" className="text-xs">
                From
              </Label>
              <Input
                id="rot-from"
                type="date"
                value={form.from}
                onChange={(e) => set("from", e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="rot-to" className="text-xs">
                To
              </Label>
              <Input
                id="rot-to"
                type="date"
                value={form.to}
                onChange={(e) => set("to", e.target.value)}
                required
              />
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Costs and fills</legend>
            {field("initialCash", "Initial cash", { min: "1", step: "1" })}
            <div className="grid grid-cols-3 gap-2">
              {field("commissionBps", "Commission bps", { min: "0", max: "1000" })}
              {field("spreadBps", "Spread bps", { min: "0", max: "1000" })}
              {field("slippageBps", "Slippage bps", { min: "0", max: "1000" })}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="rot-fees" className="text-xs">
                  Fees and taxes
                </Label>
                <select
                  id="rot-fees"
                  value={form.feeSchedule}
                  onChange={(e) => set("feeSchedule", e.target.value as Form["feeSchedule"])}
                  className={SELECT}
                >
                  {FEE_SCHEDULE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="rot-brokerage" className="text-xs">
                  Brokerage (India)
                </Label>
                <select
                  id="rot-brokerage"
                  value={form.brokerage}
                  onChange={(e) => set("brokerage", e.target.value as Form["brokerage"])}
                  className={SELECT}
                >
                  {BROKERAGE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              {field("advCapPct", "Most of 20-day traded value %", { min: "0", max: "100" })}
              <div className="space-y-1">
                <Label htmlFor="rot-fill" className="text-xs">
                  Fill at
                </Label>
                <select
                  id="rot-fill"
                  value={form.fillRule}
                  onChange={(e) => set("fillRule", e.target.value as Form["fillRule"])}
                  className={SELECT}
                >
                  <option value="next_open">Next session&apos;s open</option>
                  <option value="next_close">Next session&apos;s close</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rot-holdout" className="text-xs">
                Holdout
              </Label>
              <select
                id="rot-holdout"
                value={form.holdout}
                onChange={(e) => set("holdout", e.target.value as Form["holdout"])}
                className={SELECT}
              >
                {HOLDOUT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </fieldset>

          {state.error ? (
            <div className="border border-negative/40 bg-negative/5 px-3 py-2 text-sm" role="alert">
              <p className="font-medium">
                {state.status && state.status < 500 ? "Check the rotation" : "Run failed"}
              </p>
              <p className="mt-1 text-text-secondary">{state.error}</p>
            </div>
          ) : null}
          {problem ? (
            <p className="text-xs text-text-tertiary" data-testid="rotation-problem">
              {problem}
            </p>
          ) : null}
          <Button
            type="submit"
            disabled={pending || problem !== null}
            className="w-full rounded-sm"
          >
            {pending ? "Running…" : "Run rotation"}
          </Button>
          <p className="text-2xs text-text-tertiary">Ctrl or Cmd + Enter runs it from any field.</p>
        </form>
      </section>

      <div aria-busy={pending} aria-live="polite">
        {pending ? (
          <div className="border-y border-border-muted px-4 py-10 text-sm text-text-secondary sm:border-x sm:px-6">
            Ranking the universe at each rebalance…
          </div>
        ) : state.result && state.request ? (
          <RotationResults result={state.result} request={state.request} />
        ) : (
          <ResearchEmptyState title="No rotation run yet">
            <p>
              Rank a universe by an expression, hold the top N and rebalance on a schedule. The
              results show who was held at each rebalance, the turnover and the report card.
            </p>
          </ResearchEmptyState>
        )}
      </div>
    </div>
  );
}
