/**
 * A7.11 (M10.6): an optimiser result. Server-renderable: weights (with whole
 * shares when cash was given, and the Black-Litterman prior and posterior),
 * the fit against equal weight, the method notes and the disclaimer. Neutral
 * colours: a weight is not a gain or a loss.
 */

import { FigureStrip } from "@/components/figure-strip";
import { OPTIMISE_METHODS, type OptimiseResult, pct } from "@/lib/optimise";

function money(value: number | null | undefined, currency: string): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency, maximumFractionDigits: 2 });
}

export function OptimiseResultView({ result }: { result: OptimiseResult }) {
  const label = OPTIMISE_METHODS.find((m) => m.value === result.method)?.label ?? result.method;
  const bl = result.weights.some((w) => w.prior != null);
  const shares = result.weights.some((w) => w.shares != null);
  const p = result.performance;
  const e = result.equal_weight;
  return (
    <section className="space-y-4" data-testid="optimise-result">
      <p className="text-sm text-text-secondary">
        {label} over {result.sessions} common sessions ({result.first} to {result.last}),{" "}
        {result.currency}.
      </p>
      <FigureStrip
        label="Optimised portfolio, in-sample"
        figures={[
          {
            label: "Expected Return (In-Sample)",
            value: pct(p.expected_return),
            note: `Equal weight ${pct(e.expected_return)}`,
          },
          {
            label: "Volatility",
            value: pct(p.volatility),
            note: `Equal weight ${pct(e.volatility)}`,
          },
          {
            label: "Sharpe",
            value: p.sharpe == null ? "—" : p.sharpe.toFixed(2),
            note: `Equal weight ${e.sharpe == null ? "—" : e.sharpe.toFixed(2)} · rf ${pct(result.risk_free_rate)}`,
          },
          {
            label: `Daily CVaR ${Math.round(result.beta * 100)}%`,
            value: pct(p.cvar, 2),
            note: `Equal weight ${pct(e.cvar, 2)}`,
          },
        ]}
      />
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm" data-testid="optimise-weights">
          <thead className="text-2xs text-text-tertiary">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Symbol</th>
              <th className="px-3 py-2 text-right font-medium">Weight</th>
              {bl ? (
                <>
                  <th className="px-3 py-2 text-right font-medium">Prior Return</th>
                  <th className="px-3 py-2 text-right font-medium">Posterior Return</th>
                </>
              ) : null}
              {shares ? (
                <>
                  <th className="px-3 py-2 text-right font-medium">Shares</th>
                  <th className="px-3 py-2 text-right font-medium">Price</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {result.weights.map((w) => (
              <tr key={w.ticker} className="border-t border-border" data-testid="optimise-row">
                <td className="ticker px-3 py-2 font-semibold">{w.ticker}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  <span className="inline-flex items-center justify-end gap-2">
                    <span
                      aria-hidden="true"
                      className="inline-block h-1.5 rounded-full bg-text-tertiary"
                      style={{ width: `${Math.max(2, Math.round(w.weight * 80))}px` }}
                    />
                    {pct(w.weight)}
                  </span>
                </td>
                {bl ? (
                  <>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{pct(w.prior)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {pct(w.posterior)}
                    </td>
                  </>
                ) : null}
                {shares ? (
                  <>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {w.shares ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {money(w.price, result.currency)}
                    </td>
                  </>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shares ? (
        <p className="text-xs text-text-secondary" data-testid="optimise-leftover">
          Cash left after whole shares: {money(result.leftover, result.currency)} of{" "}
          {money(result.cash, result.currency)}.
        </p>
      ) : null}
      <ul className="list-disc space-y-1 pl-5 text-2xs text-text-tertiary">
        {result.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      <p className="text-2xs text-text-tertiary" data-testid="optimise-disclaimer">
        {result.disclaimer}
      </p>
    </section>
  );
}
