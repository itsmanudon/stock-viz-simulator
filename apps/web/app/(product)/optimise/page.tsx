/**
 * /optimise — A7.11 (M10.6): portfolio weights over stored closes (HRP, min
 * volatility, max Sharpe, min CVaR, Black-Litterman). A GET form; the run
 * happens on the server against the public route. Visitor-limited.
 */

import type { Metadata } from "next";

import { OptimiseResultView } from "@/components/optimise-result";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { runOptimise } from "@/lib/api/optimise";
import {
  OPTIMISE_METHODS,
  type OptimiseParams,
  type OptimiseResult,
  errorDetail,
  optimiseRequest,
} from "@/lib/optimise";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export const metadata: Metadata = { title: "Optimiser" };

export default async function OptimisePage({
  searchParams,
}: {
  searchParams: Promise<OptimiseParams>;
}) {
  const raw = await searchParams;
  const request = optimiseRequest(raw);
  let result: OptimiseResult | null = null;
  let error: string | null = null;
  if (request) {
    const limit = await checkVisitorLimit("optimise");
    if (!limit.allowed) return <VisitorLimitNotice retryAfterSeconds={limit.retryAfterSeconds} />;
    try {
      result = await runOptimise(request);
    } catch (err) {
      error =
        (err instanceof Error ? errorDetail(err.message) : null) ??
        "The optimiser could not run just now.";
    }
  }
  const method = request?.method ?? "hrp";
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Quant Lab"
        title="Optimiser"
        description="Weights for a basket of stored symbols, fitted to their past closes. In-sample, not advice."
      />
      <form
        method="get"
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        data-testid="optimise-form"
      >
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="opt-tickers" className="text-xs">
            Symbols (2 to 30, One Currency)
          </Label>
          <Input
            id="opt-tickers"
            name="tickers"
            defaultValue={raw.tickers ?? ""}
            placeholder="AAPL, MSFT, KO, JNJ"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-method" className="text-xs">
            Method
          </Label>
          <select
            id="opt-method"
            name="method"
            defaultValue={method ?? "hrp"}
            className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm"
          >
            {OPTIMISE_METHODS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-years" className="text-xs">
            Years of History
          </Label>
          <Input id="opt-years" name="years" defaultValue={raw.years ?? "3"} inputMode="numeric" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-rf" className="text-xs">
            Risk-Free Rate (%)
          </Label>
          <Input id="opt-rf" name="rf" defaultValue={raw.rf ?? "4"} inputMode="decimal" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-maxw" className="text-xs">
            Max Weight per Symbol (%)
          </Label>
          <Input id="opt-maxw" name="maxw" defaultValue={raw.maxw ?? "100"} inputMode="decimal" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-cash" className="text-xs">
            Cash for Whole Shares (Optional)
          </Label>
          <Input id="opt-cash" name="cash" defaultValue={raw.cash ?? ""} inputMode="decimal" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="opt-views" className="text-xs">
            Views (Black-Litterman)
          </Label>
          <Input
            id="opt-views"
            name="views"
            defaultValue={raw.views ?? ""}
            placeholder="MSFT 12% 0.6, KO 5% 0.4"
          />
        </div>
        <div className="flex items-end">
          <Button type="submit">Optimise</Button>
        </div>
      </form>
      <ul
        className="grid gap-1 text-2xs text-text-tertiary sm:grid-cols-2"
        data-testid="optimise-methods"
      >
        {OPTIMISE_METHODS.map((m) => (
          <li key={m.value}>
            <span className="text-text-secondary">{m.label}:</span> {m.note}
          </li>
        ))}
      </ul>
      {error ? (
        <p className="text-sm text-negative" data-testid="optimise-error">
          {error}
        </p>
      ) : null}
      {result ? <OptimiseResultView result={result} /> : null}
      {!request && !error ? (
        <p className="text-sm text-text-secondary" data-testid="optimise-intro">
          Enter at least two symbols to fit weights.
        </p>
      ) : null}
    </div>
  );
}
