/**
 * The large figures beside each "Watch it work" animation (owner, 27 Nov
 * 2026). Each row states its numbers in one shape of its own instead of a
 * small facts line: a funnel, a scoreboard, a range bar, a hidden end date,
 * an equation, a race from one start line, rows of pips and an account value.
 *
 * All of it is real HTML text, so the canvases stay decoration (aria-hidden)
 * and the page reads the same without them. Nothing here is smaller than
 * `text-sm`; details sit in chips under the figure.
 */

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const BIG = "text-5xl font-medium tracking-[-0.04em] tabular-nums sm:text-6xl";

/** "+23.6%" / "−6.5%" with a real minus sign, from a fraction. */
export function signedPercent(fraction: number, digits = 1): string {
  const pct = fraction * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(digits)}%`;
}

function tone(value: number) {
  return value >= 0 ? "text-positive" : "text-negative";
}

/** The details under a figure: plain chips, then quieter trailing notes. */
export function Chips({ items, notes = [] }: { items: ReactNode[]; notes?: ReactNode[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-2">
      {items.map((item, index) => (
        <li
          // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered list
          key={index}
          className="rounded-full border border-border-muted bg-surface-secondary px-3 py-1 text-sm text-text-secondary"
        >
          {item}
        </li>
      ))}
      {notes.map((note, index) => (
        <li
          // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered list
          key={`n${index}`}
          className="px-1 py-1 text-sm text-text-tertiary"
        >
          {note}
        </li>
      ))}
    </ul>
  );
}

/** Screener: "25 → 1 symbol", the filters as chips. */
export function FunnelFigure({
  first,
  last,
  layers,
  asOf,
}: {
  first: number;
  last: number;
  layers: string[];
  asOf: string | null;
}) {
  return (
    <div className="grid gap-4">
      <p className="flex flex-wrap items-baseline gap-x-3 font-medium tracking-[-0.04em] tabular-nums">
        <span className="text-5xl sm:text-6xl">{first}</span>
        <span aria-hidden className="text-4xl text-text-tertiary sm:text-5xl">
          →
        </span>
        <span className="sr-only">tracked symbols narrowed to</span>
        <span className="text-prism text-5xl sm:text-6xl">{last}</span>
        <span className="text-xl tracking-[-0.02em] text-text-secondary">
          {last === 1 ? "symbol" : "symbols"}
        </span>
      </p>
      <Chips items={layers} notes={asOf ? [`Close of ${asOf}`] : []} />
    </div>
  );
}

/** Backtest: a scoreboard, strategy against buy and hold, and who won. */
export function ScoreboardFigure({
  ticker,
  strategy,
  hold,
  from,
  to,
}: {
  ticker: string;
  strategy: number;
  hold: number;
  from: string;
  to: string;
}) {
  const gap = Math.abs(strategy - hold) * 100;
  const verdict =
    gap < 0.05
      ? "A dead heat."
      : strategy > hold
        ? `The strategy won by ${gap.toFixed(1)} points.`
        : `Holding won by ${gap.toFixed(1)} points.`;
  const side = (label: string, value: number, won: boolean) => (
    <div className="grid gap-1">
      <span className={cn(BIG, won ? "text-foreground" : "text-text-tertiary")}>
        {signedPercent(value)}
      </span>
      <span className="text-sm text-text-secondary">{label}</span>
    </div>
  );
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        {side("Strategy", strategy, strategy >= hold)}
        <span aria-hidden className="pt-4 text-xl text-text-tertiary sm:pt-6">
          vs
        </span>
        {side("Buy and hold", hold, hold >= strategy)}
      </div>
      <p className="text-base text-text-secondary">{verdict}</p>
      <Chips items={[ticker, "20/50-day crossover", `${from} – ${to}`]} />
    </div>
  );
}

/** Stock page: the latest close, and where it sat in the day's range. */
export function RangeFigure({
  ticker,
  open,
  high,
  low,
  close,
  date,
  sessions,
  format,
}: {
  ticker: string;
  open: number;
  high: number;
  low: number;
  close: number;
  date: string;
  sessions: number;
  format: (value: number) => string;
}) {
  const span = high - low || 1;
  const at = (v: number) => `${((v - low) / span) * 100}%`;
  const up = close >= open;
  return (
    <div className="grid gap-4">
      <p className="flex flex-wrap items-baseline gap-x-3">
        <span className={BIG}>{format(close)}</span>
        <span className="text-xl text-text-secondary">close</span>
      </p>
      <div className="grid max-w-md gap-2">
        <div aria-hidden className="relative h-2 rounded-full bg-surface-secondary">
          <span
            className={cn(
              "absolute inset-y-0 rounded-full",
              up ? "bg-positive/60" : "bg-negative/60",
            )}
            style={{
              left: at(Math.min(open, close)),
              width: `${((Math.abs(close - open) || span * 0.01) / span) * 100}%`,
            }}
          />
          <span
            className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground"
            style={{ left: at(close) }}
          />
        </div>
        <div className="flex justify-between text-sm text-text-secondary tabular-nums">
          <span>Low {format(low)}</span>
          <span>Open {format(open)}</span>
          <span>High {format(high)}</span>
        </div>
      </div>
      <Chips items={[ticker, date]} notes={[`${sessions} stored days on the chart`]} />
    </div>
  );
}

/**
 * Replay: the start date in full, the end date held back behind a bar until
 * you point at it or tab to it, as Replay holds back the days ahead.
 */
export function HiddenEndFigure({
  ticker,
  sessions,
  from,
  to,
}: {
  ticker: string;
  sessions: number;
  from: string;
  to: string;
}) {
  return (
    <div className="grid gap-4">
      <p className="flex flex-wrap items-baseline gap-x-3 text-3xl font-medium tracking-[-0.03em] tabular-nums sm:text-4xl">
        <span>{from}</span>
        <span aria-hidden className="text-text-tertiary">
          →
        </span>
        <span className="sr-only">to</span>
        <button
          type="button"
          className="group relative inline-block cursor-help rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="text-text-secondary opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus:opacity-100">
            {to}
          </span>
          <span
            aria-hidden
            className="absolute inset-0 rounded-md bg-[repeating-linear-gradient(135deg,var(--surface-secondary)_0_6px,var(--border-muted)_6px_8px)] transition-opacity duration-300 group-hover:opacity-0 group-focus:opacity-0"
          />
        </button>
      </p>
      <Chips
        items={[ticker, `${sessions} stored daily closes`]}
        notes={["Point at the bar to see where it ends"]}
      />
    </div>
  );
}

/** Order fill: the receipt as one line of arithmetic. */
export function EquationFigure({
  ticker,
  quantity,
  price,
  date,
  format,
}: {
  ticker: string;
  quantity: number;
  price: number;
  date: string;
  format: (value: number) => string;
}) {
  return (
    <div className="grid gap-4">
      <p className="flex flex-wrap items-baseline gap-x-3 text-3xl font-medium tracking-[-0.04em] tabular-nums sm:text-4xl">
        <span className="text-text-secondary">{quantity}</span>
        <span aria-hidden className="text-text-tertiary">
          ×
        </span>
        <span className="sr-only">shares at</span>
        <span>{format(price)}</span>
        <span className="whitespace-nowrap">
          <span aria-hidden className="text-text-tertiary">
            ={" "}
          </span>
          <span className="sr-only">costs </span>
          <span className="text-prism">{format(price * quantity)}</span>
        </span>
      </p>
      <Chips
        items={[`Buy ${quantity} ${ticker}`, `${date} close`, "No fees"]}
        notes={["Example"]}
      />
    </div>
  );
}

/**
 * Compare: two bars leaving one start line at 100, gains to the right and
 * losses to the left, scaled to the larger move.
 */
export function RaceFigure({
  a,
  b,
  from,
  to,
}: {
  a: { ticker: string; change: number };
  b: { ticker: string; change: number };
  from: string;
  to: string;
}) {
  const widest = Math.max(Math.abs(a.change), Math.abs(b.change)) || 1;
  const lane = (row: { ticker: string; change: number }) => {
    const half = `${Math.max(3, (Math.abs(row.change) / widest) * 50)}%`;
    return (
      <li className="grid grid-cols-[4.5rem_minmax(0,1fr)_7rem] items-center gap-3">
        <span className="ticker text-base font-semibold">{row.ticker}</span>
        <span aria-hidden className="relative h-3">
          {/* The shared start line at 100. */}
          <span className="absolute -inset-y-2 left-1/2 w-px bg-border" />
          <span
            className={cn(
              "absolute inset-y-0 rounded-full",
              row.change >= 0 ? "left-1/2 bg-positive/70" : "right-1/2 bg-negative/70",
            )}
            style={{ width: half }}
          />
        </span>
        <span
          className={cn(
            "text-right text-3xl font-medium tracking-[-0.03em] tabular-nums",
            tone(row.change),
          )}
        >
          {signedPercent(row.change)}
        </span>
      </li>
    );
  };
  return (
    <div className="grid gap-4">
      <ul className="grid gap-3">
        {lane(a)}
        {lane(b)}
      </ul>
      <Chips items={[`Both start at 100 on ${from}`, `To ${to}`]} />
    </div>
  );
}

/** Checklist: each symbol as a row of six pips, met ones lit. */
export function PipsFigure({
  rows,
  session,
}: {
  rows: { ticker: string; score: number; max: number }[];
  session: string | null;
}) {
  return (
    <div className="grid gap-4">
      <ul className="grid gap-2.5">
        {rows.map((row) => (
          <li key={row.ticker} className="grid grid-cols-[4.5rem_auto_1fr] items-center gap-3">
            <span className="ticker text-base font-semibold">{row.ticker}</span>
            <span aria-hidden className="flex gap-1.5">
              {Array.from({ length: row.max }, (_, i) => (
                <span
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed pip slots
                  key={i}
                  className={cn(
                    "size-3.5 rounded-full",
                    i < row.score ? "bg-brand" : "border border-border bg-transparent",
                  )}
                />
              ))}
            </span>
            <span className="text-base text-text-secondary tabular-nums">
              {row.score} of {row.max} met
            </span>
          </li>
        ))}
      </ul>
      <Chips items={session ? [`Session ${session}`] : []} notes={["Not investment advice"]} />
    </div>
  );
}

/** Portfolio: what the example account is worth now, and each holding's share. */
export function AccountFigure({
  value,
  start,
  from,
  to,
  shares,
}: {
  value: number;
  start: number;
  from: string;
  to: string;
  shares: { label: string; share: number }[];
}) {
  const money = (v: number) =>
    v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const change = value / start - 1;
  return (
    <div className="grid gap-4">
      <div className="grid gap-1">
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span className={BIG}>{money(value)}</span>
          <span className={cn("text-xl tabular-nums", tone(change))}>{signedPercent(change)}</span>
        </p>
        <p className="text-base text-text-secondary">
          Example account, {money(start)} on {from}, valued at the {to} close.
        </p>
      </div>
      <Chips items={shares.map((s) => `${s.label} ${Math.round(s.share * 100)}%`)} />
    </div>
  );
}
