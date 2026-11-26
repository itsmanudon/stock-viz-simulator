/**
 * CoverageHeatmap: the most-covered tickers (rows) over the archive's last 30
 * days (columns) (news redesign, 26 Nov 2026). A cell's colour is the day's
 * net tone ((positive - negative) / headlines, Aegis's labels) and its
 * strength the number of headlines; an empty day is an outline. Each cell is
 * a link that filters the feed to that ticker and day, and its accessible
 * name says the figures in words, so colour is never the only signal.
 *
 * Server component; scrolls sideways inside its own box on phones.
 */

import Link from "next/link";

import type { NewsHeatRow } from "@/lib/api/news";
import { type NewsQuery, newsHref } from "@/lib/news-view";
import { formatCloseDate } from "@/lib/stock-workspace";

function toneColour(net: number | null | undefined): string {
  if (net == null) return "var(--text-tertiary)";
  if (net > 0.15) return "var(--positive)";
  if (net < -0.15) return "var(--negative)";
  return "var(--text-tertiary)";
}

function toneWord(net: number | null | undefined): string {
  if (net == null) return "no tone";
  if (net > 0.15) return "mostly positive";
  if (net < -0.15) return "mostly negative";
  return "balanced or neutral";
}

export function CoverageHeatmap({
  rows,
  days,
  query,
}: {
  rows: NewsHeatRow[];
  days: string[];
  query: NewsQuery;
}) {
  if (rows.length === 0 || days.length === 0) return null;
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.map((c) => c.count)));
  return (
    <section aria-labelledby="coverage-heading" data-testid="coverage-heatmap" className="min-w-0">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="coverage-heading" className="text-sm font-semibold tracking-tight">
          Coverage
        </h2>
        <p className="text-xs text-text-tertiary">
          Most-covered symbols, {formatCloseDate(days[0])} to {formatCloseDate(days.at(-1) ?? "")}.
          Colour is the day&rsquo;s tone, strength the number of headlines.
        </p>
      </div>
      <div className="overflow-x-auto rounded-md border border-border-muted bg-card p-3">
        <table className="w-full table-fixed border-separate border-spacing-[2px]">
          <caption className="sr-only">
            Headlines per symbol and day with each day&rsquo;s tone. Each cell opens that
            day&rsquo;s headlines.
          </caption>
          {/* Fixed layout reads widths from here; the header row is screen-reader only. */}
          <colgroup>
            <col className="w-20" />
            {days.map((d) => (
              <col key={d} />
            ))}
          </colgroup>
          <thead className="sr-only">
            <tr>
              <th scope="col" className="w-20">
                Symbol
              </th>
              {days.map((d) => (
                <th key={d} scope="col">
                  {formatCloseDate(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ticker}>
                <th
                  scope="row"
                  className="ticker w-20 pr-2 text-left text-xs font-semibold whitespace-nowrap"
                >
                  <Link
                    href={newsHref(query, { tickers: [row.ticker], lens: "all" })}
                    className="hover:underline"
                  >
                    {row.ticker}
                  </Link>
                  <span className="ml-1.5 font-mono text-3xs font-normal text-text-tertiary">
                    {row.total}
                  </span>
                </th>
                {row.cells.map((cell) => {
                  const label = `${row.ticker}, ${formatCloseDate(cell.date)}: ${cell.count} headline${cell.count === 1 ? "" : "s"}${cell.count ? `, ${toneWord(cell.net)}` : ""}`;
                  if (!cell.count) {
                    return (
                      <td key={cell.date} className="p-0">
                        <span
                          role="img"
                          aria-label={label}
                          title={label}
                          className="block h-5 min-w-[5px] rounded-[3px] border border-border-muted/60"
                        />
                      </td>
                    );
                  }
                  const strength = 25 + Math.round((cell.count / max) * 70);
                  return (
                    <td key={cell.date} className="p-0">
                      <Link
                        href={newsHref(query, {
                          tickers: [row.ticker],
                          lens: "all",
                          from: cell.date,
                          to: cell.date,
                        })}
                        aria-label={label}
                        title={label}
                        className="block h-5 min-w-[5px] rounded-[3px] outline-offset-1 transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-ring"
                        style={{
                          background: `color-mix(in oklab, ${toneColour(cell.net)} ${strength}%, transparent)`,
                        }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
