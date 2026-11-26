/**
 * Behaviour diagnostics (A7.6, M10.4) on the edge page: execution
 * discipline apart from outcome, the disposition index, tilt flags, weekday
 * and hour heatmaps in the venue's time, and cost leakage. Describes the
 * record; never advice. Rates need 30 closed entries.
 */

import Link from "next/link";

import type { Behaviour } from "@/lib/api/journal-edge";
import { cn } from "@/lib/utils";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`;
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);

function Heat({ cells, title }: { cells: Behaviour["by_weekday"]; title: string }) {
  const most = Math.max(1, ...cells.map((c) => Math.abs(c.net_pnl)));
  return (
    <div>
      <p className="text-xs text-text-tertiary">{title}</p>
      <ul className="mt-1 flex flex-wrap gap-1">
        {cells.map((c) => (
          <li
            key={c.key}
            className={cn(
              "min-w-16 rounded border border-border-muted px-2 py-1 text-xs",
              c.net_pnl > 0 ? "bg-positive/10" : c.net_pnl < 0 ? "bg-negative/10" : "",
            )}
            style={{ opacity: c.entries ? 0.45 + 0.55 * (Math.abs(c.net_pnl) / most) : 0.5 }}
            title={`${c.entries} entries, net ${c.net_pnl.toFixed(2)}, win rate ${pct(c.win_rate)}`}
          >
            <span className="font-medium">{c.key}</span>{" "}
            <span className="font-mono tabular-nums text-text-secondary">{c.entries}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BehaviourView({ behaviour }: { behaviour: Behaviour }) {
  const b = behaviour;
  return (
    <div className="space-y-4" data-testid="behaviour-view">
      {b.reason ? (
        <p className="text-sm text-text-secondary">{b.reason} Counts are shown.</p>
      ) : null}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div title={b.method.discipline}>
          <dt className="text-xs text-text-tertiary">Followed the plan</dt>
          <dd className="font-mono text-sm tabular-nums" data-testid="behaviour-discipline">
            {b.discipline_followed} of {b.discipline_scored} ({pct(b.discipline_rate)})
          </dd>
        </div>
        <div title={b.method.disposition_index}>
          <dt className="text-xs text-text-tertiary">Disposition index</dt>
          <dd className="font-mono text-sm tabular-nums" data-testid="behaviour-disposition">
            {num(b.disposition_index)}{" "}
            <span className="text-xs text-text-tertiary">
              (losers {num(b.avg_hold_losers, 1)}d, winners {num(b.avg_hold_winners, 1)}d)
            </span>
          </dd>
        </div>
        <div title={b.method.tilt}>
          <dt className="text-xs text-text-tertiary">Tilt flags</dt>
          <dd className="font-mono text-sm tabular-nums" data-testid="behaviour-tilt">
            {b.tilt_entries.length} ({pct(b.tilt_rate)})
          </dd>
        </div>
        <div title={b.method.cost_leakage}>
          <dt className="text-xs text-text-tertiary">
            Fees{b.fees_estimated ? " (estimated)" : ""}
          </dt>
          <dd className="font-mono text-sm tabular-nums" data-testid="behaviour-fees">
            {num(b.fees_total)} · {pct(b.fees_share_of_gross)} of gross
          </dd>
        </div>
      </dl>
      {b.tilt_entries.length ? (
        <p className="text-xs text-text-secondary">
          Flagged entries:{" "}
          {b.tilt_entries.slice(0, 12).map((id, i) => (
            <span key={id}>
              {i ? ", " : ""}
              <Link href={`/portfolio/journal/${id}`} className="underline">
                #{id}
              </Link>
            </span>
          ))}
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Heat cells={b.by_weekday} title="By weekday (venue time)" />
        <Heat cells={b.by_hour} title="By hour of the first fill (venue time)" />
      </div>
      <p className="text-xs text-text-tertiary">
        {b.method.wording}.
        {b.currencies.length > 1 ? " Several currencies: amounts are not converted." : ""}
      </p>
    </div>
  );
}
