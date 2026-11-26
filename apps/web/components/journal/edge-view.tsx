/**
 * "Is my edge real?" (A5.6, M10.3 stats): the overall strip, the table by
 * setup, tag and source, and the live-vs-backtest drift cards. Server
 * renderable (no state). Every figure comes from `/v1/journal/stats`; the
 * intervals are shown in neutral colours, never as a gain or a loss.
 */

import Link from "next/link";

import { type Figure, FigureStrip } from "@/components/figure-strip";
import { formatUtcDateTime } from "@/lib/api-time";
import {
  DRIFT_CLASS,
  DRIFT_LABEL,
  type EdgeDrift,
  type EdgeGroup,
  type EdgeStats,
  KIND_LABEL,
  days,
  edgeMoney,
  moneyInterval,
  pct,
  rInterval,
  rValue,
  ratio,
} from "@/lib/journal-edge";
import { titleCase } from "@/lib/title-case";

function countsLine(g: EdgeGroup): string {
  const parts = [`${g.wins} won`, `${g.losses} lost`];
  if (g.breakeven) parts.push(`${g.breakeven} flat`);
  return parts.join(", ");
}

/** The overall group as a figure strip, or its counts with the reason. */
export function EdgeOverview({ stats }: { stats: EdgeStats }) {
  const g = stats.overall;
  if (g.counts_only) {
    return (
      <div
        className="space-y-2 rounded-xl border border-border-muted bg-card px-4 py-4"
        data-testid="edge-overall"
        data-counts-only="true"
      >
        <p className="text-sm font-medium">
          {g.label}: {g.n} closed {g.n === 1 ? "trade" : "trades"} ({countsLine(g)})
        </p>
        <p className="text-sm text-text-secondary" data-testid="edge-counts-only">
          {g.counts_only_reason}
        </p>
      </div>
    );
  }
  const cur = g.currency;
  const figures: Figure[] = [
    { label: "Closed Trades", value: String(g.n), note: countsLine(g) },
    { label: "Win Rate", value: pct(g.win_rate), note: `Payoff ${ratio(g.payoff)}` },
    {
      label: "Expectancy",
      value: <span data-testid="edge-expectancy">{edgeMoney(g.expectancy, cur)}</span>,
      note: g.expectancy_interval
        ? `90%: ${moneyInterval(g.expectancy_interval, cur)}`
        : (g.money_note ?? "Per trade, after fees"),
    },
    {
      label: "Expectancy in R",
      value: <span data-testid="edge-expectancy-r">{rValue(g.expectancy_r)}</span>,
      note: g.expectancy_r_interval
        ? `90%: ${rInterval(g.expectancy_r_interval)}`
        : (g.r_note ?? `${g.n_r} with R`),
    },
    { label: "Profit Factor", value: ratio(g.profit_factor), note: "Gross wins / gross losses" },
    {
      label: "Plan Adherence",
      value: pct(g.adherence_rate),
      note: g.adherence_n ? `${g.adherence_n} locked plans scored` : "No locked plans scored",
    },
    { label: "Average Holding", value: days(g.avg_holding_days), note: "Entry to exit" },
    {
      label: "Total Net P&L",
      value: edgeMoney(g.total_net_pnl, cur),
      note: g.includes_imported ? "Imported charges estimated" : "After fees",
    },
  ];
  return (
    <div className="space-y-2" data-testid="edge-overall" data-counts-only="false">
      <p className="text-sm font-medium">{g.label}</p>
      <FigureStrip figures={figures} label="Overall edge figures" className="lg:grid-cols-4" />
      {g.money_note ? <p className="text-xs text-text-tertiary">{g.money_note}</p> : null}
    </div>
  );
}

function intervalCell(g: EdgeGroup, kind: "money" | "r"): string {
  return kind === "money"
    ? moneyInterval(g.expectancy_interval, g.currency)
    : rInterval(g.expectancy_r_interval);
}

/** Groups by setup, tag and source: n and the interval, or counts only. */
export function EdgeGroupsTable({ groups, caption }: { groups: EdgeGroup[]; caption: string }) {
  if (groups.length === 0) {
    return <p className="text-sm text-text-secondary">No closed trades under these filters.</p>;
  }
  return (
    <div data-testid="edge-groups">
      {/* Phones: one card per group with the same figures. */}
      <ul className="space-y-3 md:hidden">
        {groups.map((g) => (
          <li
            key={g.key}
            className="space-y-1.5 rounded-xl border border-border-muted bg-card px-4 py-3"
            data-testid="edge-group-card"
            data-counts-only={g.counts_only ? "true" : "false"}
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-medium">{g.label}</span>
              <span className="text-2xs text-text-tertiary">{KIND_LABEL[g.kind]}</span>
            </div>
            <p className="font-mono text-sm tabular-nums">
              n {g.n} · {countsLine(g)}
            </p>
            {g.counts_only ? (
              <p className="text-xs text-text-secondary">{g.counts_only_reason}</p>
            ) : (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <dt className="text-text-tertiary">Win Rate</dt>
                <dd className="font-mono tabular-nums">{pct(g.win_rate)}</dd>
                <dt className="text-text-tertiary">Expectancy</dt>
                <dd className="font-mono tabular-nums">{edgeMoney(g.expectancy, g.currency)}</dd>
                <dt className="text-text-tertiary">90% Interval</dt>
                <dd className="font-mono tabular-nums">{intervalCell(g, "money")}</dd>
                <dt className="text-text-tertiary">Expectancy in R</dt>
                <dd className="font-mono tabular-nums">{rValue(g.expectancy_r)}</dd>
                <dt className="text-text-tertiary">90% Interval (R)</dt>
                <dd className="font-mono tabular-nums">{intervalCell(g, "r")}</dd>
                <dt className="text-text-tertiary">Profit Factor</dt>
                <dd className="font-mono tabular-nums">{ratio(g.profit_factor)}</dd>
              </dl>
            )}
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto rounded-xl border border-border-muted md:block">
        <table className="w-full text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-surface-elevated text-2xs tracking-[0.02em] text-text-tertiary">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                Group
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                n
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Won / Lost
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Win Rate
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Expectancy
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                90% Interval
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                In R
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                90% Interval (R)
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Profit Factor
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Adherence
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr
                key={g.key}
                className="border-t border-border-muted"
                data-testid="edge-group-row"
                data-counts-only={g.counts_only ? "true" : "false"}
              >
                <th scope="row" className="px-3 py-2 text-left font-medium">
                  {g.label}
                  <span className="ml-2 text-2xs font-normal text-text-tertiary">
                    {KIND_LABEL[g.kind]}
                  </span>
                </th>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{g.n}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {g.wins} / {g.losses}
                </td>
                {g.counts_only ? (
                  <td colSpan={7} className="px-3 py-2 text-xs text-text-secondary">
                    {g.counts_only_reason}
                  </td>
                ) : (
                  <>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {pct(g.win_rate)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {edgeMoney(g.expectancy, g.currency)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-text-secondary tabular-nums">
                      {intervalCell(g, "money")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {rValue(g.expectancy_r)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-text-secondary tabular-nums">
                      {intervalCell(g, "r")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {ratio(g.profit_factor)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {pct(g.adherence_rate)}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({ label, live, backtest, diff }: Record<string, string>) {
  return (
    <tr className="border-t border-border-muted">
      <th scope="row" className="py-1.5 pr-3 text-left text-xs font-normal text-text-tertiary">
        {label}
      </th>
      <td className="whitespace-nowrap py-1.5 pr-3 text-right font-mono tabular-nums">{live}</td>
      <td className="whitespace-nowrap py-1.5 pr-3 text-right font-mono tabular-nums">
        {backtest}
      </td>
      <td className="whitespace-nowrap py-1.5 text-right font-mono text-text-secondary tabular-nums">
        {diff}
      </td>
    </tr>
  );
}

function signed(value: number | null | undefined, fmt: (v: number) => string): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${fmt(value)}`;
}

/** One setup version: live (journal) against its newest saved backtest. */
export function EdgeDriftCard({ drift }: { drift: EdgeDrift }) {
  const bt = drift.backtest;
  return (
    <article
      className="space-y-3 rounded-xl border border-border-muted bg-card px-4 py-4"
      data-testid="edge-drift-card"
      data-status={drift.status}
      aria-labelledby={`drift-${drift.setup_version_id}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`drift-${drift.setup_version_id}`} className="font-medium">
          {drift.label}
        </h3>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs tracking-[0.02em] ${DRIFT_CLASS[drift.status]}`}
          data-testid="edge-drift-status"
        >
          {titleCase(DRIFT_LABEL[drift.status])}
        </span>
      </div>
      <p className="text-sm text-text-secondary">{drift.text}</p>
      {bt ? (
        <>
          <table className="w-full text-sm">
            <caption className="sr-only">Live against backtest for {drift.label}</caption>
            <thead className="text-2xs tracking-[0.02em] text-text-tertiary">
              <tr>
                <th scope="col" className="pb-1 text-left font-medium">
                  Per Trade
                </th>
                <th scope="col" className="pb-1 pr-3 text-right font-medium">
                  Live
                </th>
                <th scope="col" className="pb-1 pr-3 text-right font-medium">
                  Backtest
                </th>
                <th scope="col" className="pb-1 text-right font-medium">
                  Difference
                </th>
              </tr>
            </thead>
            <tbody>
              <Row
                label="Expectancy in R"
                live={rValue(drift.live_expectancy_r)}
                backtest={rValue(bt.expectancy_r)}
                diff={signed(drift.diff_expectancy_r, (v) => `${v.toFixed(2)}R`)}
              />
              <Row
                label="Win Rate"
                live={pct(drift.live_win_rate)}
                backtest={pct(bt.win_rate)}
                diff={signed(drift.diff_win_rate, (v) => `${(v * 100).toFixed(1)} pts`)}
              />
              <Row
                label="Average Holding"
                live={days(drift.live_avg_holding_days)}
                backtest={days(bt.avg_holding_days)}
                diff={signed(drift.diff_avg_holding_days, (v) => `${v.toFixed(1)} days`)}
              />
            </tbody>
          </table>
          <p className="text-xs text-text-tertiary" data-testid="edge-drift-interval">
            Live 90% interval:{" "}
            {drift.live_interval ? rInterval(drift.live_interval) : "not shown under 30 trades"} (
            {drift.live_n_r} live trades with R). Backtest: {bt.closed_trades} closed trades on{" "}
            {bt.ticker}, saved {formatUtcDateTime(bt.created_at)}.
          </p>
          <p className="text-xs text-text-tertiary" data-testid="edge-drift-sample">
            {bt.sample_note}{" "}
            <Link
              href={`/backtest/runs/${bt.run_id}`}
              className="underline underline-offset-2 hover:text-foreground"
            >
              Open the run
            </Link>
          </p>
        </>
      ) : (
        <p className="text-xs text-text-tertiary">
          Live: {drift.live_n} closed trades, {drift.live_n_r} with R. Save a rule backtest of this
          setup to compare.
        </p>
      )}
    </article>
  );
}

export function EdgeHonesty({ notes }: { notes: string[] }) {
  return (
    <ul
      className="space-y-1 rounded-xl border border-border-muted px-4 py-3 text-xs text-text-secondary"
      data-testid="edge-honesty"
    >
      {notes.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}
