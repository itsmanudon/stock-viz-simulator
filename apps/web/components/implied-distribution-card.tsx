/**
 * A9.13 (M8.5) on the stock page's Options tab: the options' implied
 * distribution of the price at one expiry beside a lognormal at the model's
 * volatility. Neutral colours: neither curve is good or bad. Inline SVG;
 * every figure is also written as text.
 */

import type { ImpliedDistribution } from "@/lib/api/option-exposure";

const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;

/** SVG path of one density over the shared price axis (pure, for tests). */
export function densityPath(
  curve: ImpliedDistribution["curve"],
  key: "implied" | "model",
  width = 320,
  height = 120,
): string {
  if (curve.length < 2) return "";
  const xs = curve.map((c) => c.price);
  const top = Math.max(...curve.map((c) => Math.max(c.implied, c.model))) || 1;
  const x0 = xs[0];
  const span = xs[xs.length - 1] - x0 || 1;
  return curve
    .map((c, i) => {
      const x = ((c.price - x0) / span) * width;
      const y = height - (c[key] / top) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function ImpliedDistributionCard({ data }: { data: ImpliedDistribution }) {
  const d = data;
  const hasModel = d.model_quantiles.length > 0;
  return (
    <section aria-labelledby="idist-title" className="space-y-3" data-testid="implied-distribution">
      <h3 id="idist-title" className="text-base font-semibold">
        Implied vs Model Distribution
      </h3>
      <p className="text-xs text-text-secondary">
        Price at the {d.expiry} expiry ({d.days} days), from {d.strikes_used} strikes; spot{" "}
        {d.spot?.toFixed(2)}. Implied ATM volatility {pct(d.implied_atm_vol)}
        {hasModel ? `; model ${pct(d.model_vol)} (${d.model_vol_source})` : "; no model volatility"}
        .
      </p>
      <svg
        viewBox="0 0 320 120"
        className="h-32 w-full max-w-md text-foreground"
        role="img"
        aria-label="Implied density (solid) and model density (dashed)"
      >
        <path
          d={densityPath(d.curve, "implied")}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        {hasModel ? (
          <path
            d={densityPath(d.curve, "model")}
            fill="none"
            stroke="currentColor"
            strokeOpacity="0.5"
            strokeDasharray="4 3"
            strokeWidth="1.5"
          />
        ) : null}
      </svg>
      <div className="overflow-x-auto">
        <table className="text-xs" data-testid="idist-quantiles">
          <thead>
            <tr>
              <th className="pr-3 text-left font-medium">Quantile</th>
              {d.quantile_levels.map((q) => (
                <th key={q} className="px-2 text-right font-medium">
                  {Math.round(q * 100)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            <tr>
              <td className="pr-3 font-sans">Implied</td>
              {d.implied_quantiles.map((v, i) => (
                <td key={d.quantile_levels[i]} className="px-2 text-right">
                  {v.toFixed(2)}
                </td>
              ))}
            </tr>
            {hasModel ? (
              <tr>
                <td className="pr-3 font-sans">Model</td>
                {d.model_quantiles.map((v, i) => (
                  <td key={d.quantile_levels[i]} className="px-2 text-right">
                    {v.toFixed(2)}
                  </td>
                ))}
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="text-xs" data-testid="idist-tails">
        Chance of ending more than {Math.round(d.move * 100)}% below spot: implied{" "}
        {pct(d.implied_p_down)}
        {hasModel ? `, model ${pct(d.model_p_down)}` : ""}; above: implied {pct(d.implied_p_up)}
        {hasModel ? `, model ${pct(d.model_p_up)}` : ""}.
      </p>
      {d.negative_mass && d.negative_mass > 0.01 ? (
        <p className="text-2xs text-warning">
          {pct(d.negative_mass)} of the raw density was negative (an uneven smile) and was cut.
        </p>
      ) : null}
      <p className="text-2xs text-text-tertiary">{d.method}</p>
    </section>
  );
}
