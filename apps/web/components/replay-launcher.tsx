"use client";

import { useActionState, useEffect, useId, useState } from "react";

import {
  type ReplayActionState,
  createReplayAction,
  loadReplayAvailabilityAction,
} from "@/app/(product)/(authed)/replay/actions";
import { ResearchSectionHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatCurrency } from "@/lib/portfolio-view-model";
import {
  REPLAY_DEFAULT_CASH,
  REPLAY_INTERVALS,
  REPLAY_PROFILES,
  type ReplayIntervalValue,
  type ReplayProfileValue,
  replayCashPresets,
  replayProfileLabel,
} from "@/lib/replay";

type SymbolOption = { ticker: string; name: string; currency?: string };

type Range = {
  first: string;
  last: string;
  bars: number;
  currency: string;
  lagDays: number;
  /** The last end the 30-day lag allows (Indian sessions), or null. */
  maxEnd: string | null;
  feeSchedule: string;
  tradable: boolean;
  /** A6.9: "1d" plus the intraday intervals when minutes are stored. */
  intervals: string[];
  minuteFirst: string | null;
  minuteLast: string | null;
};

export function ReplayLauncher({
  symbols,
  initialTicker,
}: {
  symbols: SymbolOption[];
  initialTicker?: string;
}) {
  const fieldId = useId();
  const known = new Set(symbols.map((item) => item.ticker));
  const startingTicker =
    initialTicker && known.has(initialTicker) ? initialTicker : (symbols[0]?.ticker ?? "");
  const [ticker, setTicker] = useState(startingTicker);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [cash, setCash] = useState(REPLAY_DEFAULT_CASH);
  const [range, setRange] = useState<Range | null>(null);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const [interval, setBarInterval] = useState<ReplayIntervalValue>("1d");
  const [profile, setProfile] = useState<ReplayProfileValue>("intrabar_ohlc");
  const [state, action, pending] = useActionState<ReplayActionState, FormData>(
    createReplayAction,
    {},
  );

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setRangeError(null);
    void loadReplayAvailabilityAction(ticker).then((result) => {
      if (cancelled) return;
      if (result.error || !result.first || !result.last) {
        setRange(null);
        setRangeError(result.error ?? "No stored daily bars for that symbol.");
        return;
      }
      const first = result.first;
      const maxEnd = result.maxEnd ?? null;
      const last = maxEnd && maxEnd < result.last ? maxEnd : result.last;
      setRange({
        first,
        last,
        bars: result.bars ?? 0,
        currency: result.currency ?? "USD",
        lagDays: result.lagDays ?? 0,
        maxEnd,
        feeSchedule: result.feeSchedule ?? "none",
        tradable: result.tradable ?? true,
        intervals: result.intervals ?? ["1d"],
        minuteFirst: result.minuteFirst ?? null,
        minuteLast: result.minuteLast ?? null,
      });
      setBarInterval((current) =>
        (result.intervals ?? ["1d"]).includes(current) ? current : "1d",
      );
      setCash(result.defaultCash ?? REPLAY_DEFAULT_CASH);
      setStart((current) => (current && current >= first && current < last ? current : first));
      setEnd((current) => (current && current <= last && current > first ? current : last));
    });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const intraday = interval !== "1d" && range?.minuteFirst && range.minuteLast;
  const lowest = intraday ? (range?.minuteFirst ?? undefined) : range?.first;
  const highest = intraday ? (range?.minuteLast ?? undefined) : range?.last;
  const intervals = REPLAY_INTERVALS.filter((i) => (range?.intervals ?? ["1d"]).includes(i.value));
  const chosenProfile = REPLAY_PROFILES.find((p) => p.value === profile) ?? REPLAY_PROFILES[0];

  return (
    <section
      aria-labelledby={`${fieldId}-title`}
      className="border-y border-border-muted py-6 sm:border-x sm:px-6"
    >
      <ResearchSectionHeader
        id={`${fieldId}-title`}
        title="Start a historical replay"
        description="You will only see prices that were knowable on the replay date. The server snaps your dates to stored daily bars."
      />
      <form action={action} className="mt-5 grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-ticker`}>Symbol</Label>
            <select
              id={`${fieldId}-ticker`}
              name="ticker"
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              {symbols.map((symbol) => (
                <option key={symbol.ticker} value={symbol.ticker}>
                  {symbol.ticker} — {symbol.name}
                  {symbol.currency && symbol.currency !== "USD" ? ` (${symbol.currency})` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-start`}>Start date</Label>
              <Input
                id={`${fieldId}-start`}
                name="start"
                type="date"
                required
                min={lowest}
                max={highest}
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-end`}>End date</Label>
              <Input
                id={`${fieldId}-end`}
                name="end"
                type="date"
                required
                min={lowest}
                max={highest}
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
          </div>
          {range ? (
            <p className="text-xs leading-5 text-text-tertiary">
              Stored daily bars for {ticker}: {range.first} → {range.last} ({range.bars} bars).
              {range.minuteFirst && range.minuteLast
                ? ` Minutes: ${range.minuteFirst} → ${range.minuteLast}.`
                : ""}
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-interval`}>Bars</Label>
              <select
                id={`${fieldId}-interval`}
                name="interval"
                value={interval}
                onChange={(event) => setBarInterval(event.target.value as ReplayIntervalValue)}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                data-testid="replay-launch-interval"
              >
                {intervals.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${fieldId}-profile`}>Fill model</Label>
              <select
                id={`${fieldId}-profile`}
                name="profile"
                value={profile}
                onChange={(event) => setProfile(event.target.value as ReplayProfileValue)}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                data-testid="replay-launch-profile"
              >
                {REPLAY_PROFILES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {range && range.intervals.length === 1 ? (
            <p className="text-xs leading-5 text-text-tertiary">
              No minute bars are stored for {ticker}, so it replays on daily bars.
            </p>
          ) : null}
          {range?.maxEnd ? (
            <p className="text-xs leading-5 text-text-secondary" data-testid="replay-lag-note">
              Indian sessions must end at least {range.lagDays} days before today, so the latest end
              is {range.maxEnd}.
            </p>
          ) : null}
          {range && !range.tradable ? (
            <p className="text-xs leading-5 text-text-secondary">
              {ticker} is an index: you can replay its chart, but not trade it.
            </p>
          ) : null}
          {rangeError ? <p className="text-sm text-negative">{rangeError}</p> : null}
        </div>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-cash`}>Starting cash ({range?.currency ?? "USD"})</Label>
            <Input
              id={`${fieldId}-cash`}
              name="starting_cash"
              type="number"
              min="1"
              step="1"
              required
              value={cash}
              onChange={(event) => setCash(event.target.value)}
            />
            <div className="flex flex-wrap gap-1.5">
              {replayCashPresets(range?.currency ?? "USD").map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setCash(preset)}
                  className="h-7 rounded-md border border-border-muted px-2 text-xs text-text-secondary hover:text-foreground"
                >
                  {formatCurrency(preset, range?.currency ?? "USD").replace(/\.00$/, "")}
                </button>
              ))}
            </div>
          </div>
          <div className="border-y border-border-muted py-3 text-xs leading-5 text-text-tertiary sm:border-x sm:px-3">
            <p>
              Execution profile:{" "}
              <span
                className="font-medium text-foreground"
                data-testid="replay-launch-profile-name"
              >
                {replayProfileLabel(chosenProfile.value, chosenProfile.version)}
              </span>
            </p>
            <p className="mt-1">{chosenProfile.description}</p>
            <p className="mt-1">
              {interval === "1d" ? "Daily-bar" : "Intraday"} simulation. No future data. No spread
              or slippage.
            </p>
            {range && range.feeSchedule !== "none" ? (
              <p className="mt-1">
                Fills pay the exchange&apos;s delivery charges in force on each date.
              </p>
            ) : null}
            <p className="mt-1">Replay cash is isolated from your live paper portfolio.</p>
          </div>
          {state.error ? (
            <p role="alert" className="text-sm text-negative">
              {state.error}
            </p>
          ) : null}
          <Button type="submit" disabled={pending || !ticker} className="w-full">
            {pending ? "Opening replay…" : "Start replay"}
          </Button>
        </div>
      </form>
    </section>
  );
}
