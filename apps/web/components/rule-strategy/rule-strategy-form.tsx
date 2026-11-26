"use client";

/**
 * A4.1 (M7.1): the Rule strategy mode of /backtest. Entry and exit rules in
 * the Rule DSL (typed, or loaded from a setup), stops, sizing, a universe
 * (one ticker, a watchlist of yours, or a list), costs; results beside it.
 * The run goes through a server action (`runStrategyAction`) so watchlists
 * and your own setups work. Ctrl/Cmd+Enter runs it from any field.
 */

import { useCallback, useMemo, useState } from "react";

import {
  type StrategyRunState,
  runStrategyAction,
} from "@/app/(product)/backtest/strategy-actions";
import { ResearchEmptyState } from "@/components/research-page-header";
import { RuleFieldEditor, type StrategySetupOption } from "@/components/rule-strategy/rule-field";
import { RuleStrategyResults } from "@/components/rule-strategy/rule-strategy-results";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type BacktestSymbol,
  defaultBacktestRange,
  pickBacktestTicker,
} from "@/lib/backtest-defaults";
import { BROKERAGE_OPTIONS, DEFAULT_ADV_CAP_PCT, FEE_SCHEDULE_OPTIONS } from "@/lib/fees";
import { HOLDOUT_OPTIONS, type HoldoutMode } from "@/lib/report-card";
import {
  type StrategyForm,
  type StrategyRequest,
  buildStrategyRequest,
  formProblem,
} from "@/lib/rule-strategy";

export type StrategyWatchlist = { id: number; name: string; count: number };

const SELECT = "flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm";

export function initialStrategyForm(
  ticker: string,
  range: { from: string; to: string },
): StrategyForm {
  return {
    entry: { text: "close crosses_above sma(close, 50)", versionId: null },
    exit: { text: "close crosses_below sma(close, 50)", versionId: null },
    universeKind: "ticker",
    ticker,
    watchlistId: "",
    tickerList: "",
    from: range.from,
    to: range.to,
    initialCash: "100000",
    fillRule: "next_open",
    feeSchedule: "auto",
    brokerage: "zerodha",
    advCapPct: DEFAULT_ADV_CAP_PCT,
    commissionBps: "0",
    slippageBps: "0",
    spreadBps: "0",
    useFixed: false,
    fixedPct: "8",
    useAtr: true,
    atrMultiple: "2",
    atrPeriod: "14",
    useTrail: false,
    trailKind: "atr",
    trailValue: "3",
    trailPeriod: "14",
    useTime: false,
    timeBars: "20",
    sizing: "fixed_risk",
    fraction: "20",
    riskPct: "1",
    maxPositions: "5",
    direction: "long",
    shortable: "",
    holdout: "last_20pct",
  };
}

export function RuleStrategyForm({
  symbols,
  initialTicker,
  setups,
  watchlists,
  signedIn,
  run = runStrategyAction,
}: {
  symbols: BacktestSymbol[];
  initialTicker?: string;
  setups: StrategySetupOption[];
  watchlists: StrategyWatchlist[];
  signedIn: boolean;
  run?: (request: StrategyRequest) => Promise<StrategyRunState>;
}) {
  const lastCloseOf = useMemo(
    () => new Map(symbols.map((s) => [s.ticker, s.lastClose])),
    [symbols],
  );
  const start = pickBacktestTicker(symbols, initialTicker);
  const [form, setForm] = useState<StrategyForm>(() =>
    initialStrategyForm(start, defaultBacktestRange(lastCloseOf.get(start))),
  );
  const [entryValid, setEntryValid] = useState(true);
  const [exitValid, setExitValid] = useState(true);
  const [pending, setPending] = useState(false);
  const [state, setState] = useState<StrategyRunState & { request?: StrategyRequest }>({});

  const set = useCallback(
    <K extends keyof StrategyForm>(key: K, value: StrategyForm[K]) =>
      setForm((f) => ({ ...f, [key]: value })),
    [],
  );
  const onEntryValidity = useCallback((v: boolean) => setEntryValid(v), []);
  const onExitValidity = useCallback((v: boolean) => setExitValid(v), []);
  const problem = formProblem(form, entryValid && exitValid);

  async function submit() {
    if (problem || pending) return;
    const request = buildStrategyRequest(form);
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

  const check = (key: keyof StrategyForm, label: string) => (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={Boolean(form[key])}
        onChange={(e) => set(key, e.target.checked as never)}
      />
      {label}
    </label>
  );
  const numberField = (
    key: keyof StrategyForm,
    label: string,
    props: Record<string, string> = {},
  ) => (
    <div className="space-y-1">
      <Label htmlFor={`rs-${key}`} className="text-xs">
        {label}
      </Label>
      <Input
        id={`rs-${key}`}
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
        aria-labelledby="rule-setup-heading"
        className="border-y border-border-muted sm:border-x"
      >
        <div className="border-b border-border-muted px-4 py-3">
          <h2 id="rule-setup-heading" className="text-sm font-semibold">
            Rule strategy
          </h2>
          <p className="mt-1 text-xs leading-5 text-text-tertiary">
            Rules are judged on each completed daily bar; orders fill on the next bar. A missing
            value is unknown and does nothing.
          </p>
        </div>
        <form
          className="space-y-5 p-4"
          onKeyDown={onKeyDown}
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <RuleFieldEditor
            label="Entry rule"
            hint="Enter when this turns true."
            value={form.entry}
            onChange={(v) => set("entry", v)}
            onValidity={onEntryValidity}
            setups={setups}
          />
          <RuleFieldEditor
            label="Exit rule"
            hint="Optional. Stops can close a position on their own."
            value={form.exit}
            onChange={(v) => set("exit", v)}
            onValidity={onExitValidity}
            setups={setups}
            optional
          />

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Universe</legend>
            <div className="flex flex-wrap gap-3 text-sm" role="radiogroup" aria-label="Universe">
              {(
                [
                  ["ticker", "One symbol"],
                  ["watchlist", "Watchlist"],
                  ["list", "Ticker list"],
                ] as const
              ).map(([kind, label]) => (
                <label key={kind} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="universe"
                    checked={form.universeKind === kind}
                    disabled={kind === "watchlist" && !signedIn}
                    onChange={() => set("universeKind", kind)}
                  />
                  {label}
                </label>
              ))}
            </div>
            {form.universeKind === "ticker" ? (
              <select
                aria-label="Symbol"
                value={form.ticker}
                onChange={(e) => {
                  const ticker = e.target.value;
                  setForm((f) => ({
                    ...f,
                    ticker,
                    ...defaultBacktestRange(lastCloseOf.get(ticker)),
                  }));
                }}
                className={SELECT}
              >
                {symbols.map((s) => (
                  <option key={s.ticker} value={s.ticker}>
                    {s.ticker} — {s.name}
                  </option>
                ))}
              </select>
            ) : null}
            {form.universeKind === "watchlist" ? (
              watchlists.length ? (
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
              )
            ) : null}
            {form.universeKind === "list" ? (
              <div className="space-y-1">
                <Label htmlFor="rs-list" className="text-xs">
                  Tickers (up to 50, one currency)
                </Label>
                <Input
                  id="rs-list"
                  value={form.tickerList}
                  onChange={(e) => set("tickerList", e.target.value)}
                  placeholder="AAPL, MSFT, NVDA"
                />
              </div>
            ) : null}
            {!signedIn ? (
              <p className="text-xs text-text-tertiary">
                Sign in to run a strategy on a watchlist.
              </p>
            ) : null}
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="rs-from" className="text-xs">
                From
              </Label>
              <Input
                id="rs-from"
                type="date"
                value={form.from}
                onChange={(e) => set("from", e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="rs-to" className="text-xs">
                To
              </Label>
              <Input
                id="rs-to"
                type="date"
                value={form.to}
                onChange={(e) => set("to", e.target.value)}
                required
              />
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Stops</legend>
            <p className="text-xs text-text-tertiary">
              Judged on each bar&apos;s high and low; a gap through a stop fills at the open. The
              stop nearest the open is hit first.
            </p>
            {check("useFixed", "Fixed % from entry")}
            {form.useFixed
              ? numberField("fixedPct", "Stop %", { min: "0.1", max: "90", step: "0.1" })
              : null}
            {check("useAtr", "ATR multiple")}
            {form.useAtr ? (
              <div className="grid grid-cols-2 gap-2">
                {numberField("atrMultiple", "Multiple", { min: "0.1", max: "20", step: "0.1" })}
                {numberField("atrPeriod", "ATR period", { min: "1", max: "250", step: "1" })}
              </div>
            ) : null}
            {check("useTrail", "Trailing stop")}
            {form.useTrail ? (
              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <Label htmlFor="rs-trail-kind" className="text-xs">
                    By
                  </Label>
                  <select
                    id="rs-trail-kind"
                    value={form.trailKind}
                    onChange={(e) => set("trailKind", e.target.value as "atr" | "pct")}
                    className={SELECT}
                  >
                    <option value="atr">ATR</option>
                    <option value="pct">%</option>
                  </select>
                </div>
                {numberField("trailValue", form.trailKind === "atr" ? "Multiple" : "Percent", {
                  min: "0.1",
                  max: "50",
                  step: "0.1",
                })}
                {form.trailKind === "atr"
                  ? numberField("trailPeriod", "ATR period", { min: "1", max: "250", step: "1" })
                  : null}
              </div>
            ) : null}
            {check("useTime", "Time stop")}
            {form.useTime
              ? numberField("timeBars", "Exit after bars", { min: "1", max: "2000", step: "1" })
              : null}
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Sizing</legend>
            <select
              aria-label="Sizing"
              value={form.sizing}
              onChange={(e) => set("sizing", e.target.value as StrategyForm["sizing"])}
              className={SELECT}
            >
              <option value="fixed_risk">Fixed risk per trade (% of equity at the stop)</option>
              <option value="fixed_fraction">Fixed fraction of equity</option>
              <option value="all_in">All in (a basket splits cash over its slots)</option>
            </select>
            {form.sizing === "fixed_risk"
              ? numberField("riskPct", "Risk % of equity", { min: "0.1", max: "10", step: "0.1" })
              : null}
            {form.sizing === "fixed_fraction"
              ? numberField("fraction", "Fraction of equity %", { min: "1", max: "100", step: "1" })
              : null}
            {form.universeKind !== "ticker"
              ? numberField("maxPositions", "Max positions", { min: "1", max: "50", step: "1" })
              : null}
            <p className="text-xs text-text-tertiary">
              Whole shares, never more than the free cash.
            </p>
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Costs and fills</legend>
            {numberField("initialCash", "Initial cash", { min: "1", step: "1" })}
            <div className="grid grid-cols-3 gap-2">
              {numberField("commissionBps", "Commission bps", { min: "0", max: "1000" })}
              {numberField("spreadBps", "Spread bps", { min: "0", max: "1000" })}
              {numberField("slippageBps", "Slippage bps", { min: "0", max: "1000" })}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="rs-fees" className="text-xs">
                  Fees and taxes
                </Label>
                <select
                  id="rs-fees"
                  value={form.feeSchedule}
                  onChange={(e) =>
                    set("feeSchedule", e.target.value as StrategyForm["feeSchedule"])
                  }
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
                <Label htmlFor="rs-brokerage" className="text-xs">
                  Brokerage (India)
                </Label>
                <select
                  id="rs-brokerage"
                  value={form.brokerage}
                  onChange={(e) => set("brokerage", e.target.value as StrategyForm["brokerage"])}
                  className={SELECT}
                >
                  {BROKERAGE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              {numberField("advCapPct", "Most of 20-day traded value %", { min: "0", max: "100" })}
              <div className="space-y-1">
                <Label htmlFor="rs-fill" className="text-xs">
                  Fill at
                </Label>
                <select
                  id="rs-fill"
                  value={form.fillRule}
                  onChange={(e) => set("fillRule", e.target.value as StrategyForm["fillRule"])}
                  className={SELECT}
                >
                  <option value="next_open">Next bar&apos;s open</option>
                  <option value="next_close">Next bar&apos;s close</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rs-direction" className="text-xs">
                Direction
              </Label>
              <select
                id="rs-direction"
                value={form.direction}
                onChange={(e) => set("direction", e.target.value as "long" | "short")}
                className={SELECT}
              >
                <option value="long">Long only</option>
                <option value="short">Short (US symbols you declare shortable)</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rs-holdout" className="text-xs">
                Holdout
              </Label>
              <select
                id="rs-holdout"
                value={form.holdout ?? "last_20pct"}
                onChange={(e) => set("holdout", e.target.value as HoldoutMode)}
                className={SELECT}
                aria-describedby="rs-holdout-hint"
              >
                {HOLDOUT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <p id="rs-holdout-hint" className="text-2xs text-text-tertiary">
                The run, sweeps and walk-forwards use the first 80% of the dates until you unlock
                the rest once.
              </p>
            </div>
            {form.direction === "short" ? (
              <div className="space-y-1">
                <Label htmlFor="rs-shortable" className="text-xs">
                  Shortable tickers (US only; every symbol in the universe)
                </Label>
                <Input
                  id="rs-shortable"
                  value={form.shortable}
                  onChange={(e) => set("shortable", e.target.value)}
                  placeholder="AAPL, MSFT"
                />
              </div>
            ) : null}
          </fieldset>

          {state.error ? (
            <div className="border border-negative/40 bg-negative/5 px-3 py-2 text-sm" role="alert">
              <p className="font-medium">
                {state.status && state.status < 500 ? "Check the strategy" : "Run failed"}
              </p>
              <p className="mt-1 text-text-secondary">{state.error}</p>
            </div>
          ) : null}
          {problem ? (
            <p className="text-xs text-text-tertiary" data-testid="strategy-problem">
              {problem}
            </p>
          ) : null}
          <Button
            type="submit"
            disabled={pending || problem !== null}
            className="w-full rounded-sm"
          >
            {pending ? "Running…" : "Run strategy"}
          </Button>
          <p className="text-2xs text-text-tertiary">Ctrl or Cmd + Enter runs it from any field.</p>
        </form>
      </section>

      <div aria-busy={pending} aria-live="polite">
        {pending ? (
          <div className="border-y border-border-muted px-4 py-10 text-sm text-text-secondary sm:border-x sm:px-6">
            Running the rules over stored daily bars…
          </div>
        ) : state.result && state.request ? (
          <RuleStrategyResults result={state.result} request={state.request} />
        ) : (
          <ResearchEmptyState title="No strategy run yet">
            <p>
              Write an entry rule (and optionally an exit), pick stops and sizing, and run it on one
              symbol, a watchlist or a list. Trades are shown on the price chart.
            </p>
          </ResearchEmptyState>
        )}
      </div>
    </div>
  );
}
