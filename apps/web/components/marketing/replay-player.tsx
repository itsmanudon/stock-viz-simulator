"use client";

/**
 * The Replay product page's player (owner, 28 Nov 2026): a small working
 * replay over real stored bars instead of a picture of one.
 *
 * - Play reveals one bar at a time (and pauses at the last stored bar),
 *   Rewind goes back to the opening bars, Step moves one bar.
 * - Buy holds a paper position at the bar in view; its change follows the
 *   replay, and Sell closes it at the close in view. Nothing is stored.
 * - The scale is set by the bars seen so far, so the hidden future cannot
 *   leak through the axis (the same rule as Replay Lab).
 * - Every figure is also text (the status line and the position line, read
 *   politely to screen readers); the chart is decoration.
 */

import { Pause, Play, Rewind, StepForward } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { emitSound } from "@/components/sound/sound-provider";
import { cn } from "@/lib/utils";

const TICK_MS = 380;

export type ReplayBar = { close: number; date: string | null };

function money(v: number) {
  return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function signedPct(v: number) {
  const pct = v * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
}

export function ReplayPlayer({ ticker, bars }: { ticker: string; bars: ReplayBar[] }) {
  const start = Math.max(2, Math.floor(bars.length * 0.25));
  const [step, setStep] = useState(Math.max(2, Math.floor(bars.length * 0.6)));
  const [playing, setPlaying] = useState(false);
  const [entry, setEntry] = useState<{ step: number; price: number } | null>(null);
  const [closed, setClosed] = useState<{ pct: number; price: number } | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const last = bars.length;
  const atEnd = step >= last;
  const close = bars[step - 1].close;

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setPlaying(false);
  }, []);

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => {
      setStep((s) => {
        if (s + 1 >= last) {
          stop();
          return last;
        }
        return s + 1;
      });
    }, TICK_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, last, stop]);

  const togglePlay = () => {
    if (playing) return stop();
    if (atEnd) setStep(start);
    setPlaying(true);
  };
  const rewind = () => {
    stop();
    setStep(start);
    setEntry(null);
    setClosed(null);
  };
  const forward = () => {
    stop();
    setStep((s) => Math.min(last, s + 1));
  };
  const buy = () => {
    setEntry({ step, price: close });
    setClosed(null);
    emitSound("fill");
  };
  const sell = () => {
    if (!entry) return;
    setClosed({ pct: close / entry.price - 1, price: close });
    setEntry(null);
    emitSound("success");
  };

  const width = 340;
  const height = 150;
  const { path, cursorX, entryPoint } = useMemo(() => {
    const seen = bars.slice(0, step).map((b) => b.close);
    const min = Math.min(...seen);
    const max = Math.max(...seen);
    const span = max - min || 1;
    const x = (i: number) => 4 + (i / (last - 1)) * (width - 8);
    const y = (v: number) => 10 + (1 - (v - min) / span) * (height - 20);
    const d = seen.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    return {
      path: d,
      cursorX: x(step - 1),
      entryPoint: entry ? { x: x(entry.step - 1), y: y(entry.price) } : null,
    };
  }, [bars, step, last, entry]);

  const open = entry ? close / entry.price - 1 : null;
  const position =
    open !== null
      ? `Holding since ${money(entry?.price ?? 0)}: ${signedPct(open)}`
      : closed !== null
        ? `Closed at ${money(closed.price)}: ${signedPct(closed.pct)}`
        : "No position. Buy at the bar in view.";

  return (
    <div className="dark grid w-full max-w-sm gap-3 rounded-3xl border border-border bg-card p-4 text-foreground shadow-2xl shadow-black/30">
      <div className="flex justify-between gap-3 text-sm">
        <span className="ticker font-semibold">{ticker} · Replay</span>
        <span className="text-text-tertiary tabular-nums" aria-live="polite">
          Bar {step} of {last}
          {bars[step - 1].date ? ` · ${bars[step - 1].date}` : ""}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" aria-hidden="true">
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.8" />
        <line
          x1={cursorX}
          x2={cursorX}
          y1="6"
          y2={height - 6}
          stroke="var(--border)"
          strokeDasharray="3 4"
        />
        {entryPoint ? (
          <circle cx={entryPoint.x} cy={entryPoint.y} r="4" fill="var(--brand)" />
        ) : null}
        {cursorX < width - 90 ? (
          <text x={cursorX + 12} y={height / 2} fill="var(--text-tertiary)" fontSize="12">
            Future hidden
          </text>
        ) : null}
      </svg>
      <p
        className={cn(
          "text-sm tabular-nums",
          open !== null || closed !== null
            ? (open ?? closed?.pct ?? 0) >= 0
              ? "text-positive"
              : "text-negative"
            : "text-text-tertiary",
        )}
        aria-live="polite"
      >
        {position}
      </p>
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={rewind}
            aria-label="Rewind to the start"
            className="grid size-10 place-items-center rounded-full border border-border-muted transition-colors hover:border-border focus-visible:outline-2 focus-visible:outline-ring"
          >
            <Rewind className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={togglePlay}
            aria-label={playing ? "Pause" : "Play"}
            className="grid size-10 place-items-center rounded-full bg-primary text-primary-foreground transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-ring"
          >
            {playing ? (
              <Pause className="size-4" aria-hidden />
            ) : (
              <Play className="size-4" aria-hidden />
            )}
          </button>
          <button
            type="button"
            onClick={forward}
            disabled={atEnd}
            aria-label="Step forward one bar"
            className="grid size-10 place-items-center rounded-full border border-border-muted transition-colors hover:border-border focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-40"
          >
            <StepForward className="size-4" aria-hidden />
          </button>
        </div>
        <div className="flex gap-2 text-sm font-medium">
          <button
            type="button"
            onClick={sell}
            disabled={!entry}
            className="rounded-full border border-border-muted px-4 py-2 transition-colors hover:border-border focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-40"
          >
            Sell
          </button>
          <button
            type="button"
            onClick={buy}
            disabled={Boolean(entry)}
            className="rounded-full bg-primary px-4 py-2 text-primary-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-40"
          >
            Buy
          </button>
        </div>
      </div>
    </div>
  );
}
