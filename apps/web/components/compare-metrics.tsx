import Link from "next/link";

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
    <div className="overflow-x-auto border-y border-border-muted">
      <table className="w-full min-w-[44rem] text-sm">
        <caption className="sr-only">
          Comparison metrics for the selected symbols over the current window.
        </caption>
        <thead>
          <tr className="border-b border-border-muted text-left text-[10px] font-semibold tracking-[0.12em] text-text-tertiary uppercase">
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
            <tr key={row.ticker} className="border-b border-border-muted last:border-0">
              <th scope="row" className="px-3 py-3 text-left font-medium">
                <Link
                  href={`/stocks/${row.ticker}`}
                  className="inline-flex items-center gap-2 hover:underline"
                >
                  <span
                    className="size-2 rounded-full"
                    style={{ backgroundColor: row.color }}
                    aria-hidden
                  />
                  <span className="font-mono">{row.ticker}</span>
                </Link>
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
            </tr>
          ))}
        </tbody>
      </table>
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
