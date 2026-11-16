import type { PortfolioStress, StressScenario } from "@/lib/api/trading";
import {
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * Phase 8.4: what today's holdings would lose in past crises and in fixed
 * shocks, applied instantly. The method is written above the table, and
 * each row says which holdings were proxied or had no history (UX-9).
 */
export function PortfolioStressPanel({
  stress,
  open,
}: {
  stress: PortfolioStress | null;
  open: boolean;
}) {
  if (!open) return null;
  if (!stress) {
    return (
      <section className="border-t border-border-muted py-5">
        <h3 className="text-sm font-semibold">Stress tests</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Stress tests are unavailable right now. Try again shortly.
        </p>
      </section>
    );
  }
  const historical = stress.scenarios.filter((s) => s.kind === "historical");
  const hypothetical = stress.scenarios.filter((s) => s.kind !== "historical");
  return (
    <section aria-labelledby="stress-heading" className="border-t border-border-muted py-5">
      <h3 id="stress-heading" className="text-sm font-semibold">
        Stress tests
      </h3>
      <p className="mt-1 text-2xs text-text-tertiary">
        Method: {stress.basis}. In {stress.currency}.
      </p>
      <div className="mt-3 grid gap-6 lg:grid-cols-2">
        <StressTable label="Past crises" rows={historical} ccy={stress.currency} />
        <StressTable label="Fixed shocks" rows={hypothetical} ccy={stress.currency} />
      </div>
    </section>
  );
}

function StressTable({ label, rows, ccy }: { label: string; rows: StressScenario[]; ccy: string }) {
  return (
    <table aria-label={label} className="w-full text-sm">
      <caption className="mb-1 text-left text-2xs font-medium text-text-tertiary">{label}</caption>
      <thead>
        <tr className="text-left text-2xs text-text-tertiary">
          <th className="py-1.5 font-medium">Scenario</th>
          <th className="py-1.5 text-right font-medium">Change</th>
          <th className="py-1.5 text-right font-medium">Value after</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-t border-border-muted align-top">
            <td className="py-2">
              <span>{row.name}</span>
              {row.start && row.end ? (
                <span className="block text-2xs text-text-tertiary">
                  {formatCloseDate(row.start)} to {formatCloseDate(row.end)}
                </span>
              ) : null}
              {row.drivers.length > 0 ? (
                <span className="block text-2xs text-text-tertiary">
                  Most of it:{" "}
                  {row.drivers
                    .slice(0, 3)
                    .map((d) => `${d.ticker} ${formatSignedCurrency(d.change, ccy)}`)
                    .join(" · ")}
                </span>
              ) : null}
              {row.proxied.length > 0 ? (
                <span className="block text-2xs text-text-tertiary">
                  Index and beta used for {row.proxied.join(", ")}
                </span>
              ) : null}
              {row.missing.length > 0 ? (
                <span className="block text-2xs text-text-tertiary">
                  No history, left unmoved: {row.missing.join(", ")}
                </span>
              ) : null}
            </td>
            <td className="py-2 text-right font-mono" data-financial>
              {formatSignedCurrency(row.change, ccy)}
              <span className="block text-2xs text-text-tertiary">
                {formatSignedPercent(row.change_pct)}
              </span>
            </td>
            <td className="py-2 text-right font-mono" data-financial>
              {formatCurrency(row.nav_after, ccy)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
