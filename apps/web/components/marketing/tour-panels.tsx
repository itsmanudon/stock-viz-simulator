/**
 * The three panels behind the product tour.
 *
 * Each one is a live recreation of a real workspace surface, not a screenshot:
 * every number comes from a public `/v1` endpoint at render time. That keeps
 * the tour honest (no invented returns, no fabricated portfolio), keeps it
 * crisp at any DPR, and means it themes itself instead of needing a light and
 * a dark capture per tab.
 *
 * They all render inside `.panel-inset`, so the dark-side tokens are already
 * rebound and ordinary workspace classes resolve correctly.
 */

import { Check, Minus, X } from "lucide-react";

import { Sparkline } from "@/components/sparkline";
import type {
  BacktestResult,
  ChecklistDimension,
  ChecklistRow,
  ScreenerResult,
} from "@/lib/api/types";
import { STATUS_LABEL } from "@/lib/checklist-view";

/** For values the API already expresses in percent (momentum). */
function pct(n: number): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

/**
 * For the backtest summary, where `total_return`, `benchmark_return`, and
 * `max_drawdown` are FRACTIONS, not percents (see the engine's
 * `_max_drawdown` docstring). Mirrors `backtest-form.tsx` so the tour and the
 * real page can never disagree about a number.
 */
function fracPct(fraction: number): string {
  const value = fraction * 100;
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toneFor(n: number): string {
  return n >= 0 ? "text-positive" : "text-negative";
}

/** Shared column shell so all three panels sit on the same internal grid. */
function PanelBody({ children }: { children: React.ReactNode }) {
  return <div className="min-h-[19rem] p-4 sm:min-h-[21rem] sm:p-5">{children}</div>;
}

function PanelHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-4">
      <p className="font-mono text-3xs tracking-[0.14em] text-brand uppercase">{eyebrow}</p>
      <p className="mt-1 text-sm text-text-secondary">{title}</p>
    </div>
  );
}

// --- 01 Screen -------------------------------------------------------------

export function ScreenPanel({ rows }: { rows: ScreenerResult[] }) {
  return (
    <PanelBody>
      <PanelHeading
        eyebrow="Screener · RSI + momentum"
        title="Filter the universe down to the handful worth opening."
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] text-left">
          <thead>
            <tr className="border-b border-border-muted">
              {["Symbol", "Last", "RSI 14", "Momentum"].map((h) => (
                <th
                  key={h}
                  className="pb-2 font-mono text-3xs font-normal tracking-[0.12em] text-text-tertiary uppercase last:text-right"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ticker} className="border-b border-border-muted/60 last:border-0">
                <td className="py-2.5">
                  <span className="ticker text-xs font-semibold">{row.ticker}</span>
                  <span className="ml-2 hidden text-2xs text-text-tertiary sm:inline">
                    {row.name}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-xs tabular-nums">
                  {Number(row.last_close).toFixed(2)}
                </td>
                <td className="py-2.5 font-mono text-xs tabular-nums text-text-secondary">
                  {row.rsi_14 === null ? "—" : row.rsi_14.toFixed(1)}
                </td>
                <td
                  className={`py-2.5 text-right font-mono text-xs tabular-nums ${
                    row.momentum_pct === null ? "text-text-tertiary" : toneFor(row.momentum_pct)
                  }`}
                >
                  {row.momentum_pct === null ? "—" : pct(row.momentum_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBody>
  );
}

// --- 02 Research -----------------------------------------------------------

/**
 * The Checklist (A2.4): every one of the six dimensions is shown, including
 * the ones not met or unknown. Two rows are called out with numbered markers;
 * the annotation is rendered inline rather than over a bitmap, so it can't
 * drift out of alignment.
 */
export function ResearchPanel({
  row,
  dimensions,
}: {
  row: ChecklistRow;
  dimensions: ChecklistDimension[];
}) {
  const items = dimensions.map((dimension) => ({
    dimension,
    status: row.results.find((r) => r.key === dimension.key)?.status ?? "unknown",
  }));
  const firstMet = items.findIndex((item) => item.status === "met");
  const firstOther = items.findIndex((item) => item.status !== "met");

  const markerFor = (index: number): number | null => {
    if (index === firstMet) return 1;
    if (index === firstOther) return 2;
    return null;
  };

  return (
    <PanelBody>
      <PanelHeading
        eyebrow="Checklist · six published conditions"
        title="Every dimension is shown with its formula, including the ones not met."
      />

      <div className="mb-3 flex items-baseline gap-3">
        <span className="ticker text-sm font-semibold">{row.ticker}</span>
        <span className="font-mono text-2xs text-text-tertiary">
          {row.met} of {row.total} met · session {row.session_date}
        </span>
      </div>

      <ul className="space-y-1.5">
        {items.map(({ dimension, status }, index) => {
          const marker = markerFor(index);
          return (
            <li
              key={dimension.key}
              className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 ${
                marker ? "bg-brand/5 ring-1 ring-brand/30" : ""
              }`}
            >
              <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-surface-secondary text-text-secondary">
                {status === "met" ? (
                  <Check className="size-2.5" aria-hidden />
                ) : status === "not_met" ? (
                  <X className="size-2.5" aria-hidden />
                ) : (
                  <Minus className="size-2.5" aria-hidden />
                )}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs">{dimension.name}</span>
              <span className="text-2xs text-text-tertiary">{STATUS_LABEL[status]}</span>
              {marker ? (
                <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-brand font-mono text-3xs text-primary-foreground">
                  {marker}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 space-y-1 border-t border-border-muted pt-3">
        <p className="font-mono text-3xs text-text-tertiary">
          <span className="text-brand">1</span> — a dimension that is met, formula on the page.
        </p>
        <p className="font-mono text-3xs text-text-tertiary">
          <span className="text-brand">2</span> — one not met or unknown. It stays on screen;
          nothing is hidden. Not investment advice.
        </p>
      </div>
    </PanelBody>
  );
}

// --- 03 Simulate -----------------------------------------------------------

export function SimulatePanel({ result }: { result: BacktestResult }) {
  const navs = result.equity_curve.map((p) => Number(p.nav));
  const s = result.summary;

  const stats = [
    { label: "Return", value: fracPct(s.total_return), tone: toneFor(s.total_return) },
    { label: "Buy & hold", value: fracPct(s.benchmark_return), tone: toneFor(s.benchmark_return) },
    { label: "Sharpe", value: s.sharpe.toFixed(2), tone: "" },
    // A drawdown is always a loss: the API returns it as a positive magnitude,
    // so it's negated here rather than rendered as a gain.
    {
      label: "Max DD",
      value: `-${(s.max_drawdown * 100).toFixed(2)}%`,
      tone: "text-negative",
    },
  ];

  return (
    <PanelBody>
      <PanelHeading
        eyebrow="Backtest · SMA crossover"
        title="Read the equity curve before you commit a simulated dollar."
      />

      <div className="flex items-baseline justify-between">
        <span className="ticker text-sm font-semibold">{result.ticker}</span>
        <span className="font-mono text-2xs text-text-tertiary">
          {result.trades.length} trades · {navs.length} sessions
        </span>
      </div>

      <Sparkline
        closes={navs}
        baseline={navs[0]}
        showBaseline
        periodLabel="backtest equity"
        className="mt-3 h-32 w-full sm:h-36"
      />

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border-muted pt-4 sm:grid-cols-4">
        {stats.map((stat) => (
          <div key={stat.label}>
            <dt className="font-mono text-3xs tracking-[0.12em] text-text-tertiary uppercase">
              {stat.label}
            </dt>
            <dd className={`mt-1 font-mono text-sm tabular-nums ${stat.tone}`}>{stat.value}</dd>
          </div>
        ))}
      </dl>
    </PanelBody>
  );
}
