"use client";

import { Tabs } from "radix-ui";

import type { Fundamentals, Valuation, ValuationHistory } from "@/lib/api/fundamentals";

/**
 * Company financials on the stock page (Phase 6.4): key multiples as known
 * today, and statements by year or quarter. Every figure carries its period
 * and currency; the panel says when the source is not point-in-time and when
 * the company reports in another currency than its shares trade in.
 */
export function FundamentalsPanel({
  annual,
  quarterly,
  valuation,
  peHistory,
}: {
  annual: Fundamentals | null;
  quarterly: Fundamentals | null;
  valuation: Valuation | null;
  peHistory: ValuationHistory | null;
}) {
  const hasStatements = Boolean(annual?.rows.length || quarterly?.rows.length);
  if (!hasStatements && !valuation?.metrics.some((m) => m.value !== null)) {
    return (
      <div className="border-y border-border-muted py-6" data-testid="fundamentals-empty">
        <h3 className="text-base font-semibold">No company financials stored yet</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Financial statements are fetched weekly. Indices and commodities have none.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-8">
      {valuation ? <KeyMetrics valuation={valuation} peHistory={peHistory} /> : null}
      {hasStatements ? (
        <Tabs.Root defaultValue={annual?.rows.length ? "annual" : "quarter"}>
          <Tabs.List aria-label="Statement period" className="flex gap-2">
            {(["annual", "quarter"] as const).map((p) => (
              <Tabs.Trigger
                key={p}
                value={p}
                className="rounded-full border border-border-muted px-3 py-1 text-xs data-[state=active]:border-brand data-[state=active]:text-brand"
              >
                {p === "annual" ? "Annual" : "Quarterly"}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="annual" className="mt-3">
            <StatementTable data={annual} />
          </Tabs.Content>
          <Tabs.Content value="quarter" className="mt-3">
            <StatementTable data={quarterly} />
          </Tabs.Content>
        </Tabs.Root>
      ) : null}
      <SourceNote data={annual ?? quarterly} valuation={valuation} />
    </div>
  );
}

function fmt(value: number | string | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (unit === "x") return `${n.toFixed(1)}×`;
  if (unit === "%") return `${n.toFixed(1)}%`;
  if (unit === "shares") {
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(
      n,
    );
  }
  if (unit.endsWith("/share")) return `${unit.split("/")[0]} ${n.toFixed(2)}`;
  return `${unit} ${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(n)}`;
}

/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st, 62nd. */
export function ordinal(n: number): string {
  const teens = n % 100;
  if (teens >= 11 && teens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th"}`;
}

const KEY_METRICS = [
  "market_cap",
  "pe",
  "pb",
  "ps",
  "ev_ebitda",
  "p_fcf",
  "dividend_yield",
  "net_margin",
  "roe",
  "debt_to_equity",
  "revenue_growth",
  "net_income_growth",
];

function KeyMetrics({
  valuation,
  peHistory,
}: {
  valuation: Valuation;
  peHistory: ValuationHistory | null;
}) {
  const byKey = new Map(valuation.metrics.map((m) => [m.key, m]));
  const pe = byKey.get("pe");
  return (
    <section aria-labelledby="key-metrics">
      <h3 id="key-metrics" className="text-base font-semibold">
        Key metrics
      </h3>
      <p className="mt-1 text-xs text-text-tertiary">
        As of {valuation.as_of}
        {valuation.price_date ? `, close of ${valuation.price_date}` : ""}.{" "}
        {valuation.basis === "ttm"
          ? "Income figures are the last four quarters."
          : valuation.basis === "annual"
            ? "Income figures are the latest fiscal year."
            : ""}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border-muted bg-border-muted sm:grid-cols-3 lg:grid-cols-4">
        {KEY_METRICS.map((key) => {
          const m = byKey.get(key);
          if (!m) return null;
          return (
            <div key={key} className="bg-card p-3">
              <dt className="text-2xs text-text-tertiary">{m.label}</dt>
              <dd className="mt-1 font-mono text-sm" data-financial title={m.reason ?? undefined}>
                {fmt(m.value, m.unit)}
              </dd>
              {m.value === null && m.reason ? (
                <dd className="text-3xs text-text-tertiary">{m.reason}</dd>
              ) : null}
            </div>
          );
        })}
      </dl>
      {pe?.value !== null && pe?.value !== undefined && peHistory?.percentile != null ? (
        <p className="mt-2 text-xs text-text-secondary" data-testid="pe-percentile">
          P/E {pe.value.toFixed(1)}× is at the {ordinal(Math.round(peHistory.percentile))}{" "}
          percentile of its last {peHistory.points.length} month-ends.
        </p>
      ) : null}
    </section>
  );
}

function StatementTable({ data }: { data: Fundamentals | null }) {
  if (!data?.rows.length) {
    return <p className="text-sm text-muted-foreground">No figures for this period type.</p>;
  }
  const label = data.period === "annual" ? "Year ending" : "Quarter ending";
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">
          {data.period === "annual" ? "Annual" : "Quarterly"} figures for {data.ticker}
        </caption>
        <thead>
          <tr className="border-b border-border-muted text-left text-2xs text-text-tertiary">
            <th className="py-2 pr-4 font-medium">{label}</th>
            {data.periods.map((end) => (
              <th key={end} className="py-2 pl-4 text-right font-medium">
                {end}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.concept} className="border-b border-border-muted/60">
              <th scope="row" className="py-1.5 pr-4 text-left font-normal">
                {row.label}
                <span className="ml-1 text-3xs text-text-tertiary">{row.unit}</span>
              </th>
              {row.values.map((v, i) => (
                <td
                  key={data.periods[i]}
                  className="py-1.5 pl-4 text-right font-mono"
                  data-financial
                >
                  {fmt(v, row.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceNote({
  data,
  valuation,
}: { data: Fundamentals | null; valuation: Valuation | null }) {
  const sources = new Set([...(data?.sources ?? []), ...(valuation?.sources ?? [])]);
  const pointInTime = (data?.point_in_time ?? true) && (valuation?.point_in_time ?? true);
  const reporting = valuation?.reporting_currency;
  const trading = valuation?.trading_currency;
  return (
    <p className="text-xs leading-5 text-text-tertiary" data-testid="fundamentals-source">
      Source: {sources.size ? [...sources].join(", ") : "none"}.{" "}
      {pointInTime
        ? "Each figure is dated by its filing."
        : "Not point-in-time: yfinance gives no filing dates, so figures are dated by when StockViz fetched them."}
      {reporting && trading && reporting !== trading && valuation?.fx_rate
        ? ` Reported in ${reporting}; the shares trade in ${trading}, converted at ${Number(valuation.fx_rate).toPrecision(4)} ${reporting} per ${trading} for the multiples.`
        : ""}
    </p>
  );
}
