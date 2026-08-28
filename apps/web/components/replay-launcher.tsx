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
import { REPLAY_CASH_PRESETS, REPLAY_DEFAULT_CASH, REPLAY_PROFILE_LABEL } from "@/lib/replay";

type SymbolOption = { ticker: string; name: string };

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
  const [range, setRange] = useState<{ first: string; last: string; bars: number } | null>(null);
  const [rangeError, setRangeError] = useState<string | null>(null);
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
      const last = result.last;
      setRange({ first, last, bars: result.bars ?? 0 });
      setStart((current) => (current && current >= first ? current : first));
      setEnd((current) => (current && current <= last ? current : last));
    });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

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
                min={range?.first}
                max={range?.last}
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
                min={range?.first}
                max={range?.last}
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
          </div>
          {range ? (
            <p className="text-xs leading-5 text-text-tertiary">
              Stored daily bars for {ticker}: {range.first} → {range.last} ({range.bars} bars).
            </p>
          ) : null}
          {rangeError ? <p className="text-sm text-negative">{rangeError}</p> : null}
        </div>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={`${fieldId}-cash`}>Starting cash (USD)</Label>
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
              {REPLAY_CASH_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setCash(preset)}
                  className="h-7 rounded-md border border-border-muted px-2 text-xs text-text-secondary hover:text-foreground"
                >
                  ${Number(preset).toLocaleString("en-US")}
                </button>
              ))}
            </div>
          </div>
          <div className="border-y border-border-muted py-3 text-xs leading-5 text-text-tertiary sm:border-x sm:px-3">
            <p>
              Execution profile:{" "}
              <span className="font-medium text-foreground">{REPLAY_PROFILE_LABEL}</span>
            </p>
            <p className="mt-1">Daily-bar simulation. No future data. No spread or slippage.</p>
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
