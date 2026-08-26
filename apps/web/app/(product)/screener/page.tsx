/**
 * /screener — server-rendered stock screener.
 *
 * Filters live in search params so the URL is shareable and back/forward
 * navigation reflects the current view. The page POSTs nothing — the form
 * submits as a GET, Next re-runs the server component, and the API
 * recomputes results. No client state needed.
 */

import { ClickableRow } from "@/components/clickable-row";
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
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Screener</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Filter symbols by sector, RSI, momentum, and 52-week proximity. Filters combine with AND
          logic.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <form
          method="GET"
          action="/screener"
          className="space-y-4 rounded-lg border bg-card p-4 text-sm"
        >
          <div className="space-y-1.5">
            <Label htmlFor="sector">Sector</Label>
            <select
              id="sector"
              name="sector"
              defaultValue={sector ?? ""}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="">All sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium uppercase text-muted-foreground">
              RSI (14)
            </legend>
            <div className="flex gap-2">
              <Input
                type="number"
                name="rsi_min"
                placeholder="Min"
                min={0}
                max={100}
                step="0.1"
                defaultValue={params.rsi_min ?? ""}
              />
              <Input
                type="number"
                name="rsi_max"
                placeholder="Max"
                min={0}
                max={100}
                step="0.1"
                defaultValue={params.rsi_max ?? ""}
              />
            </div>
          </fieldset>

          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium uppercase text-muted-foreground">
              Momentum
            </legend>
            <Input
              type="number"
              name="momentum_days"
              placeholder="Window (days)"
              min={1}
              max={252}
              defaultValue={params.momentum_days ?? ""}
            />
            <div className="flex gap-2">
              <Input
                type="number"
                name="momentum_min"
                placeholder="Min %"
                step="0.1"
                defaultValue={params.momentum_min ?? ""}
              />
              <Input
                type="number"
                name="momentum_max"
                placeholder="Max %"
                step="0.1"
                defaultValue={params.momentum_max ?? ""}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Min/Max apply only when a window is set.
            </p>
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-xs font-medium uppercase text-muted-foreground">
              52-week range
            </legend>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                name="near_52w_high"
                value="true"
                defaultChecked={near52wHigh}
                className="h-4 w-4"
              />
              <span>Near 52-week high (within 5%)</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                name="near_52w_low"
                value="true"
                defaultChecked={near52wLow}
                className="h-4 w-4"
              />
              <span>Near 52-week low (within 5%)</span>
            </label>
          </fieldset>

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
          <div className="mb-3 text-sm text-muted-foreground">
            {errorMessage
              ? `Error: ${errorMessage}`
              : `${results.length} match${results.length === 1 ? "" : "es"}`}
          </div>

          {results.length === 0 && !errorMessage ? (
            <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
              No symbols match the current filters. Try widening the RSI band or removing the
              52-week constraint.
            </p>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[110px]">Ticker</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="hidden md:table-cell">Sector</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">RSI(14)</TableHead>
                    <TableHead className="text-right">
                      {momentumDays ? `${momentumDays}d %` : "Momentum"}
                    </TableHead>
                    <TableHead className="hidden text-right md:table-cell">52w Low</TableHead>
                    <TableHead className="hidden text-right md:table-cell">52w High</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((row) => {
                    const up = row.momentum_pct !== null && row.momentum_pct >= 0;
                    return (
                      <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                        <TableCell className="font-mono font-semibold">{row.ticker}</TableCell>
                        <TableCell className="truncate">{row.name}</TableCell>
                        <TableCell className="hidden text-muted-foreground md:table-cell">
                          {row.sector ?? "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          ${fmt(row.last_close)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {row.rsi_14 === null ? "—" : row.rsi_14.toFixed(1)}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono ${
                            row.momentum_pct === null
                              ? "text-muted-foreground"
                              : up
                                ? "text-green-500"
                                : "text-red-500"
                          }`}
                        >
                          {fmtPct(row.momentum_pct)}
                        </TableCell>
                        <TableCell className="hidden text-right font-mono text-muted-foreground md:table-cell">
                          ${fmt(row.low_52w)}
                        </TableCell>
                        <TableCell className="hidden text-right font-mono text-muted-foreground md:table-cell">
                          ${fmt(row.high_52w)}
                        </TableCell>
                      </ClickableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
