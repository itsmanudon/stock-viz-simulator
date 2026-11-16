import type { PortfolioAttribution, PortfolioExposure } from "@/lib/api/trading";
import { formatCurrency, formatSignedCurrency } from "@/lib/portfolio-view-model";

const DIMENSION_LABELS: Record<string, string> = {
  sector: "By sector",
  country: "By country",
  currency: "By currency",
};

/**
 * Phase 8.2: where the account's value sits. Weights are shares of NAV;
 * open options show beside them at delta-adjusted notional, which is
 * exposure rather than value, so they never add into the 100%.
 */
export function PortfolioExposurePanel({ exposure }: { exposure: PortfolioExposure | null }) {
  if (!exposure) return null;
  return (
    <section aria-labelledby="exposure-heading" className="border-t border-border-muted py-5">
      <h3 id="exposure-heading" className="text-sm font-semibold">
        Exposure
      </h3>
      <p className="mt-1 text-2xs text-text-tertiary">
        Method: {exposure.basis}. In {exposure.currency}.
      </p>
      <div className="mt-3 grid gap-5 md:grid-cols-3">
        {exposure.dimensions.map((dim) => (
          <ul
            key={dim.dimension}
            aria-label={DIMENSION_LABELS[dim.dimension] ?? dim.dimension}
            className="space-y-2"
          >
            <li className="text-2xs font-medium text-text-tertiary">
              {DIMENSION_LABELS[dim.dimension] ?? dim.dimension}
            </li>
            {dim.buckets.map((b) => (
              <li key={b.key} className="text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate">{b.key}</span>
                  <span className="font-mono" data-financial>
                    {b.weight_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div
                    className="h-full rounded-full bg-text-secondary"
                    style={{ width: `${Math.min(Math.max(b.weight_pct, 0), 100)}%` }}
                  />
                </div>
                {Number(b.options_delta) !== 0 ? (
                  <p className="mt-0.5 text-2xs text-text-tertiary">
                    Options: {formatSignedCurrency(b.options_delta, exposure.currency)} delta (
                    {b.options_delta_pct.toFixed(1)}% of NAV)
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ))}
      </div>
    </section>
  );
}

/**
 * Phase 8.2: each holding's gain since entry split into the stock's own move,
 * the currency's move and their small cross term, in the base currency.
 */
export function PortfolioAttributionPanel({
  attribution,
}: {
  attribution: PortfolioAttribution | null;
}) {
  if (!attribution || attribution.holdings.length === 0) return null;
  const ccy = attribution.currency;
  return (
    <section aria-labelledby="attribution-heading" className="border-t border-border-muted py-5">
      <h3 id="attribution-heading" className="text-sm font-semibold">
        Currency attribution
      </h3>
      <p className="mt-1 text-2xs text-text-tertiary">
        Method: {attribution.basis}. In {ccy}. Dividends are shown as income.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table aria-label="Gain by source" className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="text-left text-2xs text-text-tertiary">
              <th className="py-1.5 font-medium">Holding</th>
              <th className="py-1.5 text-right font-medium">Cost</th>
              <th className="py-1.5 text-right font-medium">Price</th>
              <th className="py-1.5 text-right font-medium">Currency</th>
              <th className="py-1.5 text-right font-medium">Cross</th>
              <th className="py-1.5 text-right font-medium">Income</th>
            </tr>
          </thead>
          <tbody>
            {attribution.holdings.map((h) => (
              <tr key={h.ticker} className="border-t border-border-muted">
                <td className="py-2">
                  <span className="ticker font-semibold">{h.ticker}</span>
                  <span className="ml-1.5 text-2xs text-text-tertiary">{h.currency}</span>
                </td>
                {h.reason ? (
                  <td colSpan={4} className="py-2 text-right text-xs text-text-tertiary">
                    {h.reason}
                  </td>
                ) : (
                  <>
                    <Money value={h.cost_base} ccy={ccy} plain />
                    <Money value={h.price_effect} ccy={ccy} />
                    <Money value={h.currency_effect} ccy={ccy} />
                    <Money value={h.cross_effect} ccy={ccy} />
                  </>
                )}
                <Money value={h.income} ccy={ccy} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Money({ value, ccy, plain }: { value: string | null; ccy: string; plain?: boolean }) {
  return (
    <td className="py-2 text-right font-mono" data-financial>
      {value === null ? "—" : plain ? formatCurrency(value, ccy) : formatSignedCurrency(value, ccy)}
    </td>
  );
}
