/**
 * The four panels behind the product tour.
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

import { Check, X } from "lucide-react";

import { Sparkline } from "@/components/sparkline";
import type { LeaderboardEntry } from "@/lib/api/leaderboard";
import type { BacktestResult, Recommendation, ScreenerResult } from "@/lib/api/types";

/** For values the API already expresses in percent (momentum, leaderboard return). */
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

function money(raw: string | number): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function toneFor(n: number): string {
  return n >= 0 ? "text-positive" : "text-negative";
}

/** Shared column shell so all four panels sit on the same internal grid. */
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
                  <span className="font-mono text-xs font-semibold">{row.ticker}</span>
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
 * The differentiator: every vote in the rule set is shown, including the ones
 * that failed. Two rows are called out with numbered markers — the annotation
 * is rendered inline rather than positioned over a bitmap, so it can't drift
 * out of alignment.
 */
export function ResearchPanel({ rec }: { rec: Recommendation }) {
  const votes = rec.votes.slice(0, 7);
  const passed = votes.filter((v) => v.passed).length;
  // Annotate the first pass and the first failure, whichever rows those are.
  const firstPass = votes.findIndex((v) => v.passed);
  const firstFail = votes.findIndex((v) => !v.passed);

  const markerFor = (index: number): number | null => {
    if (index === firstPass) return 1;
    if (index === firstFail) return 2;
    return null;
  };

  return (
    <PanelBody>
      <PanelHeading
        eyebrow="Signals · rule-based votes"
        title="Every vote is shown, so you can disagree with the ones you don't buy."
      />

      <div className="mb-3 flex items-baseline gap-3">
        <span className="font-mono text-sm font-semibold">{rec.ticker}</span>
        <span className="font-mono text-2xs text-text-tertiary">
          {passed}/{votes.length} votes passed · score {rec.score}
        </span>
      </div>

      <ul className="space-y-1.5">
        {votes.map((vote, index) => {
          const marker = markerFor(index);
          return (
            <li
              key={vote.id}
              className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 ${
                marker ? "bg-brand/5 ring-1 ring-brand/30" : ""
              }`}
            >
              <span
                className={`flex size-4 shrink-0 items-center justify-center rounded-full ${
                  vote.passed ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative"
                }`}
              >
                {vote.passed ? (
                  <Check className="size-2.5" aria-hidden />
                ) : (
                  <X className="size-2.5" aria-hidden />
                )}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs">{vote.label}</span>
              <span className="hidden truncate text-2xs text-text-tertiary sm:block sm:max-w-[45%]">
                {vote.detail}
              </span>
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
          <span className="text-brand">1</span> — a vote that passed, with the number behind it.
        </p>
        <p className="font-mono text-3xs text-text-tertiary">
          <span className="text-brand">2</span> — a vote that failed. It stays on screen; nothing is
          hidden to make the score look better.
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
        <span className="font-mono text-sm font-semibold">{result.ticker}</span>
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

// --- 04 Track --------------------------------------------------------------

export function TrackPanel({ rows }: { rows: LeaderboardEntry[] }) {
  return (
    <PanelBody>
      <PanelHeading
        eyebrow="Leaderboard · opted-in accounts"
        title="The scoreboard for the decisions you actually made."
      />
      <ul className="divide-y divide-border-muted/60">
        {rows.map((row) => (
          <li key={row.user_id} className="flex items-center gap-3 py-2.5">
            <span className="w-6 shrink-0 font-mono text-2xs text-text-tertiary tabular-nums">
              {String(row.rank).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1 truncate text-xs">{row.username}</span>
            <span className="font-mono text-xs text-text-secondary tabular-nums">
              {money(row.portfolio_value)}
            </span>
            <span
              className={`w-20 text-right font-mono text-xs tabular-nums ${toneFor(row.return_pct)}`}
            >
              {pct(row.return_pct)}
            </span>
          </li>
        ))}
      </ul>
    </PanelBody>
  );
}
