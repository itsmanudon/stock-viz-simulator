import type { PortfolioRisk } from "@/lib/api/trading";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * Phase 8.3: historical-simulation VaR and CVaR, and a block-bootstrap Monte
 * Carlo. The method, the rule, the window and any proxied or excluded
 * holdings are written next to the figures (UX-9): a risk number without its
 * method and horizon is not shown.
 */
export function PortfolioRiskPanel({
  risk,
  open,
  goal = null,
  range,
}: {
  risk: PortfolioRisk | null;
  /** False while another tab is open: the report is only loaded on Analytics. */
  open: boolean;
  /** Phase 8.6: the target value from `?goal=`, if any. */
  goal?: number | null;
  /** Kept in the goal form so submitting it does not reset the chart range. */
  range?: string;
}) {
  if (!open) return null;
  if (!risk) {
    return (
      <section className="border-t border-border-muted py-5">
        <h3 className="text-sm font-semibold">Risk</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Risk figures are unavailable right now. Try again shortly.
        </p>
      </section>
    );
  }
  const ccy = risk.currency;
  const mc = risk.monte_carlo;
  return (
    <section aria-labelledby="risk-heading" className="border-t border-border-muted py-5">
      <h3 id="risk-heading" className="text-sm font-semibold">
        Risk
      </h3>
      <p className="mt-1 text-2xs text-text-tertiary">
        Method: historical simulation of today's holdings over {risk.window.sessions} past sessions
        {risk.window.start && risk.window.end
          ? ` (${formatCloseDate(risk.window.start)} to ${formatCloseDate(risk.window.end)})`
          : ""}
        , in {ccy}. {risk.var_rule}. Options are repriced in full. Past moves, not a forecast.
      </p>
      {risk.reason ? (
        <p className="mt-3 text-sm text-muted-foreground">No risk figures yet: {risk.reason}.</p>
      ) : (
        <table aria-label="Value at risk" className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-2xs text-text-tertiary">
              <th className="py-1.5 font-medium">Confidence</th>
              <th className="py-1.5 font-medium">Horizon</th>
              <th className="py-1.5 text-right font-medium">VaR</th>
              <th className="py-1.5 text-right font-medium">CVaR</th>
              <th className="py-1.5 text-right font-medium">Scenarios</th>
            </tr>
          </thead>
          <tbody>
            {risk.var.map((v) => (
              <tr
                key={`${v.confidence}-${v.horizon_days}`}
                className="border-t border-border-muted"
              >
                <td className="py-2">{Math.round(v.confidence * 100)}%</td>
                <td className="py-2">
                  {v.horizon_days} {v.horizon_days === 1 ? "day" : "days"}
                </td>
                <td className="py-2 text-right font-mono" data-financial>
                  {formatCurrency(v.var, ccy)}{" "}
                  <span className="text-2xs text-text-tertiary">{v.var_pct.toFixed(2)}%</span>
                </td>
                <td className="py-2 text-right font-mono" data-financial>
                  {formatCurrency(v.cvar, ccy)}{" "}
                  <span className="text-2xs text-text-tertiary">{v.cvar_pct.toFixed(2)}%</span>
                </td>
                <td className="py-2 text-right text-xs text-text-secondary">
                  worst {v.tail_count} of {v.scenarios}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {mc ? (
        <div className="mt-5">
          <h4 className="text-xs font-semibold">One year ahead, resampled</h4>
          <p className="mt-1 text-2xs text-text-tertiary">
            Method: stationary block bootstrap of past daily returns (blocks of about{" "}
            {mc.mean_block} sessions), {mc.paths.toLocaleString("en-US")} paths over{" "}
            {mc.horizon_days} sessions, fixed seed. A resampling of the past, not a forecast.
          </p>
          <dl
            aria-label="Value in one year"
            className="mt-2 grid grid-cols-3 gap-3 text-sm sm:grid-cols-5"
          >
            {["5", "25", "50", "75", "95"].map((p) => (
              <div key={p}>
                <dt className="text-2xs text-text-tertiary">{p}th percentile</dt>
                <dd className="font-mono" data-financial>
                  {formatCurrency(mc.percentiles[p] ?? null, ccy)}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-text-secondary">
            Chance of losing more than 10%: {(mc.prob_loss_10 * 100).toFixed(1)}% · more than 20%:{" "}
            {(mc.prob_loss_20 * 100).toFixed(1)}%
          </p>
          <form method="get" action="/portfolio" className="mt-4 flex flex-wrap items-end gap-3">
            <input type="hidden" name="tab" value="analytics" />
            {range ? <input type="hidden" name="range" value={range} /> : null}
            <div className="grid gap-1">
              <label htmlFor="goal-value" className="text-2xs text-text-tertiary">
                Goal: account value in a year ({ccy})
              </label>
              <input
                id="goal-value"
                name="goal"
                type="number"
                inputMode="decimal"
                min="1"
                step="any"
                defaultValue={goal ?? ""}
                className="h-8 w-40 rounded-md border border-input bg-transparent px-2 font-mono text-sm"
              />
            </div>
            <button
              type="submit"
              className="h-8 rounded-full border border-border px-4 text-xs font-medium transition hover:bg-surface-secondary"
            >
              Check goal
            </button>
          </form>
          {mc.goal != null && mc.prob_goal != null ? (
            <output className="mt-2 block text-sm">
              Reaching {formatCurrency(mc.goal, ccy)} in a year: {goalOdds(mc.prob_goal)} on past
              behaviour ({(mc.prob_goal * 100).toFixed(1)}% of resampled paths).
            </output>
          ) : null}
        </div>
      ) : null}
      {risk.proxied.length > 0 || risk.excluded.length > 0 ? (
        <ul className="mt-3 space-y-0.5 text-2xs text-text-tertiary">
          {risk.proxied.map((p) => (
            <li key={`p-${p.ticker}`}>
              {p.ticker}: {p.days} early sessions use {p.proxy}, before its own history starts.
            </li>
          ))}
          {risk.excluded.map((e) => (
            <li key={`e-${e.ticker}`}>
              {e.ticker} left out: {e.reason}.
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** "about 1 in 4": a probability in words, never a promise. */
export function goalOdds(p: number): string {
  if (p >= 0.995) return "nearly every path";
  if (p <= 0.005) return "almost no path";
  if (p >= 0.5) return `about ${Math.round(p * 100)} in 100`;
  return `about 1 in ${Math.round(1 / p)}`;
}
