import type { Valuation } from "@/lib/api/fundamentals";

const ROWS: { key: string; label: string }[] = [
  { key: "market_cap", label: "Market cap" },
  { key: "pe", label: "P/E" },
  { key: "pb", label: "P/B" },
  { key: "ps", label: "P/S" },
  { key: "ev_ebitda", label: "EV/EBITDA" },
  { key: "dividend_yield", label: "Dividend yield" },
  { key: "net_margin", label: "Net margin" },
  { key: "roe", label: "Return on equity" },
  { key: "debt_to_equity", label: "Debt to equity" },
  { key: "revenue_growth", label: "Revenue growth (YoY)" },
];

function fmt(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (unit === "x") return `${value.toFixed(1)}×`;
  if (unit === "%") return `${value.toFixed(1)}%`;
  return `${unit} ${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value)}`;
}

/**
 * Fundamentals side by side on /compare (Phase 6.5). Ratios are currency-free
 * and compare directly; market cap is shown in each company's reporting
 * currency, which the header names, so a USD and an INR figure are never
 * read as one scale.
 */
export function CompareFundamentals({
  rows,
}: { rows: { ticker: string; valuation: Valuation | null }[] }) {
  if (!rows.some((r) => r.valuation?.metrics.some((m) => m.value !== null))) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="compare-fundamentals-empty">
        No company financials stored for these symbols yet.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="compare-fundamentals">
        <thead>
          <tr className="border-b border-border-muted text-left text-2xs text-text-tertiary">
            <th className="py-2 pr-4 font-medium">As known today</th>
            {rows.map((r) => (
              <th key={r.ticker} className="py-2 pl-4 text-right font-medium">
                <span className="ticker font-semibold text-foreground">{r.ticker}</span>
                <span className="block text-3xs">
                  {r.valuation?.reporting_currency
                    ? `reports in ${r.valuation.reporting_currency}`
                    : "no reports"}
                  {r.valuation && !r.valuation.point_in_time && r.valuation.sources.length
                    ? " · not point-in-time"
                    : ""}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.key} className="border-b border-border-muted/60">
              <th scope="row" className="py-1.5 pr-4 text-left font-normal">
                {row.label}
              </th>
              {rows.map((r) => {
                const m = r.valuation?.metrics.find((x) => x.key === row.key);
                return (
                  <td
                    key={r.ticker}
                    className="py-1.5 pl-4 text-right font-mono"
                    data-financial
                    title={m?.reason ?? undefined}
                  >
                    {fmt(m?.value, m?.unit ?? "x")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
