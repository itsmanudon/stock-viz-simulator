/**
 * Forecasts, scored honestly (A9.2, M8.2, M8.3), on the stock page's Research
 * tab: HAR-RV volatility against a random walk (skill above 0 beats it), and
 * conformal price cones with the share of later outcomes they covered beside
 * each nominal level.
 */

import type { Forecast } from "@/lib/api/research-views";
import { cn } from "@/lib/utils";

const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;

function Skill({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-text-tertiary">{label}</dt>
      <dd
        className={cn(
          "font-mono text-sm tabular-nums",
          value === null || value === undefined
            ? ""
            : value > 0
              ? "text-positive"
              : "text-negative",
        )}
      >
        {value === null || value === undefined
          ? "—"
          : `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`}
      </dd>
    </div>
  );
}

export function ForecastCard({ forecast }: { forecast: Forecast }) {
  const v = forecast.volatility;
  return (
    <section aria-labelledby="forecast-title" className="space-y-3" data-testid="forecast">
      <h3 id="forecast-title" className="text-base font-semibold">
        Forecasts, against a random walk
      </h3>
      {v.reason ? (
        <p className="text-sm text-text-secondary">{v.reason}</p>
      ) : (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <dt className="text-xs text-text-tertiary">Next-session volatility (annualised)</dt>
            <dd className="font-mono text-sm tabular-nums" data-testid="forecast-vol">
              {pct(v.next_day_vol)}
            </dd>
          </div>
          <Skill label="Skill vs random walk (QLIKE)" value={v.skill_qlike} />
          <Skill label="Skill vs random walk (MSE)" value={v.skill_mse} />
          <div>
            <dt className="text-xs text-text-tertiary">Scored on</dt>
            <dd className="text-sm">{v.test_days} later sessions</dd>
          </div>
        </dl>
      )}
      {forecast.cones.length ? (
        <table className="w-full max-w-xl text-xs" data-testid="forecast-cones">
          <caption className="text-left text-text-tertiary">
            Price bands from {forecast.last_close?.toFixed(2)} ({forecast.last_date})
          </caption>
          <thead>
            <tr className="text-text-tertiary">
              <th className="text-left font-normal">Horizon</th>
              <th className="text-right font-normal">Level</th>
              <th className="text-right font-normal">Band</th>
              <th className="text-right font-normal">Covered</th>
            </tr>
          </thead>
          <tbody>
            {forecast.cones.map((c) => {
              const short =
                c.realised_coverage !== null &&
                c.realised_coverage !== undefined &&
                c.realised_coverage < c.level - 0.05;
              return (
                <tr key={`${c.horizon}-${c.level}`}>
                  <td>
                    {c.horizon} session{c.horizon === 1 ? "" : "s"}
                  </td>
                  <td className="text-right">{pct(c.level, 0)}</td>
                  <td className="text-right font-mono tabular-nums">
                    {c.lower?.toFixed(2)} – {c.upper?.toFixed(2)}
                  </td>
                  <td className={cn("text-right font-mono tabular-nums", short && "text-warning")}>
                    {pct(c.realised_coverage)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : forecast.cones_reason ? (
        <p className="text-sm text-text-secondary">{forecast.cones_reason}</p>
      ) : null}
      <p className="text-xs text-text-tertiary">
        {forecast.method.scoring}. {forecast.method.honesty}.
      </p>
    </section>
  );
}
