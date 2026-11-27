/**
 * Twelve-month dividend projection (A9.6, M10.8) on the Portfolio Income tab:
 * per holding the trailing 12 months, the growth used, the next 12 months'
 * total, forward yield and growth streak, plus a payout calendar. Totals stay
 * per currency. Labelled a projection throughout.
 */

import type { HoldingProjection } from "@/lib/api/trading";
import { formatCurrency } from "@/lib/portfolio-view-model";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(2)}%`;

export function DividendProjection({
  holdings,
  totals,
  method,
}: {
  holdings: HoldingProjection[];
  totals: Record<string, string>;
  method: string;
}) {
  const paying = holdings.filter((h) => !h.reason);
  const calendar = paying
    .flatMap((h) =>
      (h.payouts ?? []).map((p) => ({ ...p, ticker: h.ticker, currency: h.currency })),
    )
    .sort((a, b) => a.ex_date.localeCompare(b.ex_date));
  return (
    <section
      aria-labelledby="dividend-projection-heading"
      className="space-y-4"
      data-testid="dividend-projection"
    >
      <div>
        <h3 id="dividend-projection-heading" className="text-sm font-semibold">
          Next 12 Months (Projection)
        </h3>
        <p className="mt-1 text-xs text-text-tertiary">{method}</p>
      </div>
      <dl className="flex flex-wrap gap-6" data-testid="projection-totals">
        {Object.entries(totals).map(([cur, amount]) => (
          <div key={cur}>
            <dt className="text-xs text-text-tertiary">Projected · {cur}</dt>
            <dd className="font-mono text-lg tabular-nums" data-financial>
              {formatCurrency(amount, cur)}
            </dd>
          </div>
        ))}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" data-testid="projection-table">
          <thead className="text-text-tertiary">
            <tr>
              <th className="text-left font-normal">Symbol</th>
              <th className="text-right font-normal">TTM / Share</th>
              <th className="text-right font-normal">Growth Used</th>
              <th className="text-right font-normal">Next 12M</th>
              <th className="text-right font-normal">Forward Yield</th>
              <th className="text-right font-normal">Streak</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr key={h.ticker} data-testid="projection-row">
                <td className="ticker font-semibold">{h.ticker}</td>
                {h.reason ? (
                  <td colSpan={5} className="text-right text-text-tertiary">
                    {h.reason}
                  </td>
                ) : (
                  <>
                    <td className="text-right font-mono tabular-nums">
                      {formatCurrency(h.ttm_per_share, h.currency)}
                    </td>
                    <td
                      className="text-right font-mono tabular-nums"
                      title={
                        h.growth_3y == null
                          ? "Under 3 years of history: 0%"
                          : `3-year rate ${pct(h.growth_3y)}`
                      }
                    >
                      {pct(h.growth_used)}
                    </td>
                    <td className="text-right font-mono tabular-nums">
                      {formatCurrency(h.next_12m_total, h.currency)}
                    </td>
                    <td className="text-right font-mono tabular-nums">{pct(h.forward_yield)}</td>
                    <td className="text-right">{h.streak_years ? `${h.streak_years} yr` : "—"}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {calendar.length ? (
        <details>
          <summary className="cursor-pointer text-xs font-medium">
            Payout calendar ({calendar.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs" data-testid="projection-calendar">
            {calendar.map((p) => (
              <li key={`${p.ticker}-${p.ex_date}`} className="flex gap-3">
                <span className="w-24 text-text-tertiary">{p.ex_date}</span>
                <span className="ticker w-16 font-semibold">{p.ticker}</span>
                <span className="font-mono tabular-nums">
                  {formatCurrency(p.amount, p.currency)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
