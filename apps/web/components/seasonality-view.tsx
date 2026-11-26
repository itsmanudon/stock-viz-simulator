/**
 * Seasonality and the post-earnings drift (A9.1, M3.6, M6.6) on the stock
 * page's Research tab. Percent returns from stored history; counts and
 * t-statistics beside every average; association, not a forecast.
 */

import { ForecastCard } from "@/components/forecast-card";
import type { EarningsDrift, Forecast, Seasonality } from "@/lib/api/research-views";
import { cn } from "@/lib/utils";

const pct = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;

function Cells({ cells }: { cells: Seasonality["months"] }) {
  return (
    <ul className="grid grid-cols-4 gap-1 sm:grid-cols-6 lg:grid-cols-12">
      {cells.map((c) => (
        <li
          key={c.key}
          className={cn(
            "rounded border border-border-muted px-2 py-1 text-center text-xs",
            (c.mean ?? 0) > 0 ? "bg-positive/10" : (c.mean ?? 0) < 0 ? "bg-negative/10" : "",
            c.thin && "opacity-60",
          )}
          title={`${c.n} returns · median ${pct(c.median)} · up ${c.hit_rate === null || c.hit_rate === undefined ? "—" : `${Math.round(c.hit_rate * 100)}%`} · t ${c.t_stat ?? "—"}${c.thin ? " · thin" : ""}`}
        >
          <div className="font-medium">{c.key}</div>
          <div className="font-mono tabular-nums">{pct(c.mean, 1)}</div>
          <div className="text-2xs text-text-tertiary">n {c.n}</div>
        </li>
      ))}
    </ul>
  );
}

export function SeasonalityView({
  seasonality,
  drift,
  forecast = null,
}: {
  seasonality: Seasonality | null;
  drift: EarningsDrift | null;
  /** A9.2: forecasts with their skill and coverage. */
  forecast?: Forecast | null;
}) {
  return (
    <div className="space-y-8">
      {forecast ? <ForecastCard forecast={forecast} /> : null}
      {seasonality ? (
        <section aria-labelledby="season-title" className="space-y-2" data-testid="seasonality">
          <h3 id="season-title" className="text-base font-semibold">
            Seasonality
          </h3>
          <p className="text-xs text-text-tertiary">
            Average return by calendar month{seasonality.first ? ` since ${seasonality.first}` : ""}
            .
          </p>
          <Cells cells={seasonality.months} />
          <p className="pt-2 text-xs text-text-tertiary">By weekday</p>
          <Cells cells={seasonality.weekdays} />
          <p className="text-xs text-text-tertiary">{seasonality.note}</p>
        </section>
      ) : null}
      {drift?.events.length ? (
        <section aria-labelledby="drift-title" className="space-y-2" data-testid="earnings-drift">
          <h3 id="drift-title" className="text-base font-semibold">
            Earnings reactions and drift
          </h3>
          <p className="text-sm" data-testid="drift-summary">
            Average move on the reaction session{" "}
            <span className="font-mono">{pct(drift.avg_abs_reaction)}</span> against{" "}
            <span className="font-mono">{pct(drift.avg_abs_day)}</span> on an average day, over{" "}
            {drift.events.length} reports.
          </p>
          <table className="w-full max-w-lg text-xs">
            <thead>
              <tr className="text-text-tertiary">
                <th className="text-left font-normal">After a</th>
                <th className="text-right font-normal">+1 session</th>
                <th className="text-right font-normal">+5</th>
                <th className="text-right font-normal">+20</th>
              </tr>
            </thead>
            <tbody>
              {drift.groups.map((g) => (
                <tr key={g.group}>
                  <th className="text-left font-normal">
                    {g.group === "beat" ? "Beat" : g.group === "miss" ? "Miss" : "No surprise data"}
                  </th>
                  {g.horizons.map((h) => (
                    <td
                      key={h.sessions}
                      className="text-right font-mono tabular-nums"
                      title={`n ${h.n}, t ${h.t_stat ?? "—"}`}
                    >
                      {pct(h.mean)} <span className="text-text-tertiary">({h.n})</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-text-tertiary">{drift.note}</p>
        </section>
      ) : null}
    </div>
  );
}
