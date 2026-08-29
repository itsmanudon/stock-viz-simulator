import Link from "next/link";

import { ClickableRow } from "@/components/clickable-row";
import type { CompareInsight, CompareMetrics } from "@/lib/compare-workspace";
import { formatSignedNumber, formatSignedPct } from "@/lib/compare-workspace";
import { cn } from "@/lib/utils";

function cell(value: string, className?: string) {
  return <span className={cn("font-mono text-xs tabular-nums", className)}>{value}</span>;
}

function signedClass(value: number | null): string {
  if (value === null) return "text-muted-foreground";
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-foreground";
}

export function CompareMetricsTable({ rows }: { rows: CompareMetrics[] }) {
  return (
    <>
      <div className="divide-y divide-border-muted border-y border-border-muted md:hidden">
        {rows.map((row) => (
          <article key={row.ticker} className="py-3.5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <Link
                  href={`/stocks/${row.ticker}`}
                  className="inline-flex items-center gap-2 font-mono text-sm font-semibold hover:text-brand"
                >
                  <span
                    className="size-2 rounded-full"
                    style={{ backgroundColor: row.color }}
                    aria-hidden
                  />
                  {row.ticker}
                </Link>
                <p className="mt-0.5 truncate text-xs text-text-tertiary">{row.name}</p>
              </div>
              <div className="shrink-0 text-right font-mono text-sm" data-financial>
                {row.lastPrice === null ? "—" : row.lastPrice.toFixed(2)}
                <p className={cn("mt-0.5 text-xs", signedClass(row.returnPct))}>
                  {row.returnPct === null ? "—" : formatMobilePct(row.returnPct)}
                </p>
              </div>
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-x-3 gap-y-2 border-t border-border-muted pt-2.5">
              <CompareMetric
                label="Volatility"
                value={row.volatilityPct === null ? "—" : `${row.volatilityPct.toFixed(1)}%`}
              />
              <CompareMetric
                label="Drawdown"
                value={row.maxDrawdownPct === null ? "—" : `-${row.maxDrawdownPct.toFixed(2)}%`}
                tone="negative"
              />
              <CompareMetric
                label="RSI 14"
                value={row.rsi14 === null ? "—" : row.rsi14.toFixed(1)}
              />
              <CompareMetric
                label="52w pos."
                value={
                  row.week52PositionPct === null ? "—" : `${row.week52PositionPct.toFixed(0)}%`
                }
              />
              <CompareMetric
                label="Sentiment"
                value={row.sentiment7d === null ? "—" : formatSignedNumber(row.sentiment7d)}
                tone={signedClass(row.sentiment7d)}
              />
              <CompareMetric label="Sector" value={row.sector ?? "—"} />
            </dl>
          </article>
        ))}
      </div>

      <div className="hidden overflow-x-auto rounded-md border border-border-muted bg-card md:block">
        <table className="w-full min-w-[44rem] text-sm">
          <caption className="sr-only">
            Comparison metrics for the selected symbols over the current window.
          </caption>
          <thead>
            <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
              <th scope="col" className="px-3 py-2.5">
                Symbol
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Last
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Window return
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Window vol
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Max drawdown
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                RSI 14
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                52w pos.
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Sentiment
              </th>
              <th scope="col" className="px-3 py-2.5">
                Sector
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                <th scope="row" className="px-3 py-3 text-left font-medium">
                  <span className="inline-flex items-center gap-2 hover:text-brand">
                    <span
                      className="size-2 rounded-full"
                      style={{ backgroundColor: row.color }}
                      aria-hidden
                    />
                    <span className="font-mono">{row.ticker}</span>
                  </span>
                  <div className="mt-0.5 truncate pl-4 text-xs font-normal text-text-tertiary">
                    {row.name}
                  </div>
                </th>
                <td className="px-3 py-3 text-right">
                  {cell(row.lastPrice === null ? "—" : row.lastPrice.toFixed(2))}
                </td>
                <td className={cn("px-3 py-3 text-right", signedClass(row.returnPct))}>
                  {cell(row.returnPct === null ? "—" : formatSignedPct(row.returnPct))}
                </td>
                <td className="px-3 py-3 text-right">
                  {cell(row.volatilityPct === null ? "—" : `${row.volatilityPct.toFixed(1)}%`)}
                </td>
                <td className="px-3 py-3 text-right text-negative">
                  {cell(row.maxDrawdownPct === null ? "—" : `-${row.maxDrawdownPct.toFixed(2)}%`)}
                </td>
                <td className="px-3 py-3 text-right">
                  {cell(row.rsi14 === null ? "—" : row.rsi14.toFixed(1))}
                </td>
                <td className="px-3 py-3 text-right">
                  {cell(
                    row.week52PositionPct === null ? "—" : `${row.week52PositionPct.toFixed(0)}%`,
                  )}
                </td>
                <td className={cn("px-3 py-3 text-right", signedClass(row.sentiment7d))}>
                  {cell(row.sentiment7d === null ? "—" : formatSignedNumber(row.sentiment7d))}
                </td>
                <td className="px-3 py-3 text-xs text-text-secondary">{row.sector ?? "—"}</td>
              </ClickableRow>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function formatMobilePct(value: number): string {
  return formatSignedPct(value).replace("%", " %");
}

function CompareMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-3xs font-semibold tracking-[0.1em] text-text-tertiary uppercase">
        {label}
      </dt>
      <dd className={cn("mt-0.5 truncate font-mono text-xs", tone)} data-financial>
        {value}
      </dd>
    </div>
  );
}

export function CompareInsights({ insights }: { insights: CompareInsight[] }) {
  if (insights.length === 0) return null;
  return (
    <section aria-labelledby="compare-insights-heading">
      <h2 id="compare-insights-heading" className="text-sm font-semibold tracking-tight">
        Relative observations
      </h2>
      <p className="mt-1 text-xs text-text-tertiary">
        Deterministic facts from the selected window and available metrics. Not commentary.
      </p>
      <ul className="mt-3 divide-y divide-border-muted border-y border-border-muted">
        {insights.map((insight) => (
          <li key={insight.id} className="py-2.5 text-sm leading-6">
            {insight.text}
          </li>
        ))}
      </ul>
    </section>
  );
}
