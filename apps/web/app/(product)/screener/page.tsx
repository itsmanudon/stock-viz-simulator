/**
 * /screener — server-rendered stock screener.
 *
 * Filters live in search params so the URL is shareable and back/forward
 * navigation reflects the current view. The page POSTs nothing — the form
 * submits as a GET, Next re-runs the server component, and the API
 * recomputes results. No client state needed.
 */

import { ClickableRow } from "@/components/clickable-row";
import { DataTableFrame, NumericCell } from "@/components/data-table";
import { ResearchPageHeader } from "@/components/research-page-header";
import { type SymbolCardData, SymbolCardList } from "@/components/symbol-card-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, listSymbols, screenSymbols } from "@/lib/api";

type SearchParams = {
  sector?: string;
  rsi_min?: string;
  rsi_max?: string;
  momentum_days?: string;
  momentum_min?: string;
  momentum_max?: string;
  near_52w_high?: string;
  near_52w_low?: string;
};

function num(s: string | undefined): number | undefined {
  if (s === undefined || s === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

function fmt(n: string | number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

export default async function ScreenerPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;

  const sector = params.sector || undefined;
  const rsiMin = num(params.rsi_min);
  const rsiMax = num(params.rsi_max);
  const momentumDays = num(params.momentum_days);
  const momentumMin = num(params.momentum_min);
  const momentumMax = num(params.momentum_max);
  const near52wHigh = params.near_52w_high === "true";
  const near52wLow = params.near_52w_low === "true";
  const activeFilterCount = [
    sector,
    rsiMin,
    rsiMax,
    momentumDays,
    momentumMin,
    momentumMax,
    near52wHigh ? true : undefined,
    near52wLow ? true : undefined,
  ].filter((value) => value !== undefined).length;

  const allSymbols = await listSymbols();
  const sectors = Array.from(
    new Set(allSymbols.map((s) => s.sector).filter((s): s is string => Boolean(s))),
  ).sort();

  let results: Awaited<ReturnType<typeof screenSymbols>> = [];
  let errorMessage: string | null = null;
  try {
    results = await screenSymbols({
      sector,
      rsiMin,
      rsiMax,
      momentumDays,
      momentumMin,
      momentumMax,
      near52wHigh,
      near52wLow,
    });
  } catch (err) {
    if (err instanceof ApiError) {
      errorMessage = err.message;
    } else {
      throw err;
    }
  }

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <ResearchPageHeader
        title="Screener"
        description="Filter symbols by sector, RSI, momentum, and 52-week proximity. Filters combine with AND logic."
      />

      <div className="mt-5 grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-7">
        <form
          method="GET"
          action="/screener"
          className="space-y-4 rounded-md border border-border-muted bg-card p-4 text-sm"
        >
          <div className="flex items-start justify-between gap-3 border-b border-border-muted pb-3">
            <div>
              <p className="text-2xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                Filters
              </p>
              <p className="mt-1 text-xs text-text-secondary">Combine with AND logic</p>
            </div>
            {activeFilterCount ? (
              <span className="rounded-md bg-brand-muted px-2 py-1 text-2xs font-semibold text-brand">
                {activeFilterCount} active
              </span>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sector">Sector</Label>
            <select
              id="sector"
              name="sector"
              defaultValue={sector ?? ""}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
            >
              <option value="">All sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <details className="group rounded-md border border-border-muted/70 px-3 py-2 lg:border-0 lg:px-0 lg:py-0">
            <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.1em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
              RSI (14)
            </summary>
            <fieldset className="mt-2 space-y-1.5">
              <legend className="sr-only">RSI (14)</legend>
              <div className="flex gap-2">
                <Input
                  type="number"
                  name="rsi_min"
                  aria-label="Minimum RSI"
                  placeholder="Min"
                  min={0}
                  max={100}
                  step="0.1"
                  defaultValue={params.rsi_min ?? ""}
                />
                <Input
                  type="number"
                  name="rsi_max"
                  aria-label="Maximum RSI"
                  placeholder="Max"
                  min={0}
                  max={100}
                  step="0.1"
                  defaultValue={params.rsi_max ?? ""}
                />
              </div>
            </fieldset>
          </details>

          <details className="group rounded-md border border-border-muted/70 px-3 py-2 lg:border-0 lg:px-0 lg:py-0">
            <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.1em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
              Momentum
            </summary>
            <fieldset className="mt-2 space-y-1.5">
              <legend className="sr-only">Momentum</legend>
              <Input
                type="number"
                name="momentum_days"
                aria-label="Momentum window in days"
                placeholder="Window (days)"
                min={1}
                max={252}
                defaultValue={params.momentum_days ?? ""}
              />
              <div className="flex gap-2">
                <Input
                  type="number"
                  name="momentum_min"
                  aria-label="Minimum momentum percent"
                  placeholder="Min %"
                  step="0.1"
                  defaultValue={params.momentum_min ?? ""}
                />
                <Input
                  type="number"
                  name="momentum_max"
                  aria-label="Maximum momentum percent"
                  placeholder="Max %"
                  step="0.1"
                  defaultValue={params.momentum_max ?? ""}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Min/Max apply only when a window is set.
              </p>
            </fieldset>
          </details>

          <details className="group rounded-md border border-border-muted/70 px-3 py-2 lg:border-0 lg:px-0 lg:py-0">
            <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.1em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
              52-week range
            </summary>
            <fieldset className="mt-2 space-y-2">
              <legend className="sr-only">52-week range</legend>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  name="near_52w_high"
                  value="true"
                  defaultChecked={near52wHigh}
                  className="h-4 w-4 accent-brand"
                />
                <span>Near 52-week high (within 5%)</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  name="near_52w_low"
                  value="true"
                  defaultChecked={near52wLow}
                  className="h-4 w-4 accent-brand"
                />
                <span>Near 52-week low (within 5%)</span>
              </label>
            </fieldset>
          </details>

          <div className="flex gap-2 pt-2">
            <Button type="submit" className="flex-1">
              Apply
            </Button>
            <Button type="button" variant="outline" asChild>
              <a href="/screener">Reset</a>
            </Button>
          </div>
        </form>

        <section>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span className="text-text-secondary">
              {errorMessage
                ? `Error: ${errorMessage}`
                : `${results.length} match${results.length === 1 ? "" : "es"}`}
            </span>
            <span className="text-xs text-text-tertiary">
              {activeFilterCount
                ? `${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"}`
                : "All symbols"}
            </span>
          </div>

          {results.length === 0 && !errorMessage ? (
            <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
              No symbols match the current filters. Try widening the RSI band or removing the
              52-week constraint.
            </p>
          ) : (
            <>
              {/* Cards below lg, table above — see the markets page for why
                  the switch is lg rather than md. */}
              <SymbolCardList
                className="lg:hidden"
                rows={results.map(
                  (row): SymbolCardData => ({
                    ticker: row.ticker,
                    name: row.name,
                    price: `$${fmt(row.last_close)}`,
                    changePct: row.momentum_pct,
                    changeLabel: row.momentum_pct === null ? null : fmtPct(row.momentum_pct),
                    metrics: [
                      {
                        label: "RSI 14",
                        value: row.rsi_14 === null ? "—" : row.rsi_14.toFixed(1),
                      },
                      { label: "52w Low", value: `$${fmt(row.low_52w)}` },
                      { label: "52w High", value: `$${fmt(row.high_52w)}` },
                    ],
                  }),
                )}
              />

              <DataTableFrame className="hidden lg:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[110px]">Ticker</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead className="hidden 2xl:table-cell">Sector</TableHead>
                      <TableHead className="text-right">Price</TableHead>
                      <TableHead className="text-right">RSI(14)</TableHead>
                      <TableHead className="text-right">
                        {momentumDays ? `${momentumDays}d %` : "Momentum"}
                      </TableHead>
                      <TableHead className="hidden text-right 2xl:table-cell">52w Low</TableHead>
                      <TableHead className="hidden text-right 2xl:table-cell">52w High</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((row) => (
                      <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                        <TableCell className="font-mono font-semibold">{row.ticker}</TableCell>
                        <TableCell className="truncate">{row.name}</TableCell>
                        <TableCell className="hidden text-text-tertiary 2xl:table-cell">
                          {row.sector ?? "—"}
                        </TableCell>
                        <NumericCell>${fmt(row.last_close)}</NumericCell>
                        <NumericCell>
                          {row.rsi_14 === null ? null : row.rsi_14.toFixed(1)}
                        </NumericCell>
                        <NumericCell signedBy={row.momentum_pct}>
                          {row.momentum_pct === null ? null : fmtPct(row.momentum_pct)}
                        </NumericCell>
                        <NumericCell muted className="hidden 2xl:table-cell">
                          ${fmt(row.low_52w)}
                        </NumericCell>
                        <NumericCell muted className="hidden 2xl:table-cell">
                          ${fmt(row.high_52w)}
                        </NumericCell>
                      </ClickableRow>
                    ))}
                  </TableBody>
                </Table>
              </DataTableFrame>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
