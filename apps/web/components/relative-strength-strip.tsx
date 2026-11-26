import type { RelativeStrength } from "@/lib/api/chart-context";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * A3.5 (M2.7): RS percentile over 1, 3, 6 and 12 months against the
 * symbol's market, and the distance from the 52-week high, with the
 * universe stamp. Neutral: a percentile is a rank, not a signal.
 */

const PERIOD_LABEL: Record<string, string> = { "1m": "1M", "3m": "3M", "6m": "6M", "12m": "12M" };
const MARKET: Record<string, string> = { US: "US", IN: "Indian" };

const SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };

export function ordinal(n: number): string {
  const r = Math.round(n);
  const teen = r % 100 >= 11 && r % 100 <= 13;
  return `${r}${teen ? "th" : (SUFFIX[r % 10] ?? "th")}`;
}

function signedPct(value: number): string {
  const text = `${Math.abs(value).toFixed(1)}%`;
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

export function RelativeStrengthStrip({ strength }: { strength: RelativeStrength }) {
  const market = strength.market ? MARKET[strength.market] : null;
  const date = strength.as_of ? formatCloseDate(strength.as_of) : null;
  return (
    <section
      aria-label="Relative strength"
      className="border-b border-border-muted"
      data-testid="relative-strength"
    >
      <dl className="grid grid-cols-2 divide-x divide-y divide-border-muted sm:grid-cols-5 sm:divide-y-0">
        {strength.periods.map((p) => (
          <div key={p.period} className="min-w-0 px-3 py-3 sm:px-4">
            <dt className="text-3xs leading-4 font-semibold tracking-[0.02em] text-text-tertiary">
              RS Rank {PERIOD_LABEL[p.period] ?? p.period}
            </dt>
            <dd
              className="mt-1 font-mono text-sm font-medium tabular-nums text-foreground"
              title={
                p.return_pct === null || p.return_pct === undefined
                  ? "No return over this period"
                  : `${signedPct(p.return_pct)} over ${p.sessions} sessions`
              }
            >
              {p.percentile === null || p.percentile === undefined ? "—" : ordinal(p.percentile)}
              {p.return_pct === null || p.return_pct === undefined ? null : (
                <span className="ml-1.5 text-2xs text-text-tertiary">
                  {signedPct(p.return_pct)}
                </span>
              )}
            </dd>
          </div>
        ))}
        <div className="col-span-2 min-w-0 px-3 py-3 sm:col-span-1 sm:px-4">
          <dt className="text-3xs leading-4 font-semibold tracking-[0.02em] text-text-tertiary">
            From 52-Week High
          </dt>
          <dd className="mt-1 font-mono text-sm font-medium tabular-nums text-foreground">
            {strength.distance_from_high_52w_pct === null ||
            strength.distance_from_high_52w_pct === undefined
              ? "—"
              : signedPct(strength.distance_from_high_52w_pct)}
          </dd>
        </div>
      </dl>
      <p
        className="px-3 pb-2.5 text-2xs leading-4 text-text-tertiary sm:px-4"
        data-testid="rs-universe"
      >
        {market && strength.universe.size
          ? `Percentile of the return among ${strength.universe.size} ${market} symbols${
              date ? ` on ${date}` : ""
            } (100th = strongest; vs ${strength.benchmark_name ?? strength.benchmark} the order is the same). ${strength.universe.note}`
          : (strength.reason ?? "No relative strength for this symbol.")}
      </p>
    </section>
  );
}
