/**
 * /screener — server-rendered stock screener.
 *
 * Filters live in search params so the URL is shareable and back/forward
 * navigation reflects the current view. The page POSTs nothing — the form
 * submits as a GET, Next re-runs the server component, and the API
 * recomputes results. No client state needed.
 *
 * Phase 6.2: reads /v1/screener, which filters every symbol before paging
 * (audit RS-5), sorts on the server and covers both markets (market,
 * currency, trend and volatility filters). Signed-in users can save screens.
 *
 * A2.2: a Rule DSL rule (`?rule=`, `?rule_mode=met_only|all`) refines the
 * filters. The API judges it on every candidate before paging; rows carry
 * met / not met / unknown with the reason, and every page the universe stamp.
 */

import { X } from "lucide-react";

import { auth } from "@/auth";
import type { Metadata } from "next";
import Link from "next/link";

import { BulkAddToWatchlist, type ListChoice } from "@/components/add-to-list";
import { ClickableRow } from "@/components/clickable-row";
import { DataTableFrame, NumericCell, SortableHead } from "@/components/data-table";
import { RangeBar, rangePositionPct } from "@/components/range-bar";
import { ResearchPageHeader } from "@/components/research-page-header";
import { RulePanel, type RulePreset } from "@/components/rule-panel";
import { SavedScreens } from "@/components/saved-screens";
import { ScreenBasket } from "@/components/screen-basket";
import { CardSortBar, type SymbolCardData, SymbolCardList } from "@/components/symbol-card-list";
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
import { UniverseNote } from "@/components/universe-note";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import {
  ApiError,
  type ScreenerPage as ScreenerPageData,
  type ScreenerRow,
  getScreenerPage,
  listSymbols,
} from "@/lib/api";
import { getAiStatus } from "@/lib/api/ai";
import { getKiteHandoff } from "@/lib/api/brokers";
import { getScreenerPageAsUser } from "@/lib/api/screener-server";
import { type SavedScreen, listSavedScreens } from "@/lib/api/screens";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { listPresets } from "@/lib/api/setups";
import { listWatchlists } from "@/lib/api/watchlist";
import type { KiteHandoff } from "@/lib/basket";
import { buildCompareHref } from "@/lib/compare-workspace";
import { formatCurrency } from "@/lib/portfolio-view-model";
import {
  MARKET_LABEL,
  RULE_RESULT_LABEL,
  type ScreenerParams,
  type ScreenerSortKey,
  activeFilterChips,
  activeRule,
  carriedFields,
  clearFiltersHref,
  clearRuleHref,
  describeRuleError,
  parseRuleMode,
  parseScreenerPage,
  parseScreenerSort,
  ruleErrorFromMessage,
  ruleModeHref,
  savedScreenQuery,
  screenerApiQuery,
  screenerPageHref,
  screenerSortHref,
} from "@/lib/screener-view";
import { formatCloseDate } from "@/lib/stock-workspace";
import { checkVisitorLimit } from "@/lib/visitor-limit";
import { draftRuleAction } from "./actions";

export const metadata: Metadata = { title: "Screener" };

const PAGE_SIZE = 50;

function num(s: string | undefined): number | undefined {
  if (s === undefined || s === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

function formatCompactUsd(n: number | null): string | null {
  if (n === null || !Number.isFinite(n)) return null;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

export default async function ScreenerPage({
  searchParams,
}: {
  searchParams: Promise<ScreenerParams>;
}) {
  const params = await searchParams;
  const visitorLimit = await checkVisitorLimit("screener");
  if (!visitorLimit.allowed) {
    return <VisitorLimitNotice retryAfterSeconds={visitorLimit.retryAfterSeconds} />;
  }

  const sector = params.sector || undefined;
  const momentumDays = num(params.momentum_days);
  const near52wHigh = params.near_52w_high === "true";
  const near52wLow = params.near_52w_low === "true";
  const chips = activeFilterChips(params);
  const activeFilterCount = chips.length;
  const { sort, dir } = parseScreenerSort(params);
  const direction = (key: ScreenerSortKey) => (sort === key ? dir : null);

  const allSymbols = await listSymbols();
  const sectors = Array.from(
    new Set(allSymbols.map((s) => s.sector).filter((s): s is string => Boolean(s))),
  ).sort();

  const rule = activeRule(params);
  const ruleMode = parseRuleMode(params);
  let results: ScreenerRow[] = [];
  let total = 0;
  let errorMessage: string | null = null;
  let screen: ScreenerPageData | null = null;
  // A3.3: a rule runs as the signed-in user, so rules that read their
  // drawings (drawing(), avwap()) resolve on theirs and nobody else's.
  const session = await auth();
  const signedIn = Boolean(session?.user?.id);
  const asUser = signedIn && Boolean(rule);
  try {
    const query = screenerApiQuery(params, PAGE_SIZE);
    screen = asUser ? await getScreenerPageAsUser(query) : await getScreenerPage(query);
    results = screen.rows;
    total = screen.total;
  } catch (err) {
    if (err instanceof ApiError || err instanceof AuthedApiError) {
      const status = err.status;
      const ruleError = rule ? ruleErrorFromMessage(err.message) : null;
      errorMessage = ruleError
        ? `Rule: ${describeRuleError(ruleError)}`
        : status === 401 && rule
          ? "This rule reads your drawings (drawing() or avwap()). Sign in to run it."
          : err.message;
    } else if (err instanceof UnauthenticatedError) {
      errorMessage = "Sign in to run this rule.";
    } else {
      throw err;
    }
  }
  const ruleRun = screen?.rule ?? null;
  let presets: RulePreset[] = [];
  try {
    presets = (await listPresets()).map((p) => ({
      id: p.id,
      name: p.name,
      description: p.description ?? null,
      rule: p.latest_version.rule_text,
    }));
  } catch {
    presets = [];
  }
  // A8.2: "Describe in words" shows only when the server has a model.
  const ai = signedIn ? await getAiStatus().catch(() => null) : null;
  const aiModel = ai?.configured ? `${ai.provider} ${ai.model}` : null;
  const pageNumber = parseScreenerPage(params);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  let savedScreens: SavedScreen[] = [];
  // A2.5: the lists the bulk "Add to list" offers (signed in only).
  let watchlists: ListChoice[] = [];
  // A6.11: Kite's basket form for the screen's basket (only with KITE_API_KEY).
  let kite: KiteHandoff = null;
  if (signedIn) {
    const [screensResult, listsResult, kiteResult] = await Promise.all([
      listSavedScreens().catch(() => [] as SavedScreen[]),
      listWatchlists().catch(() => []),
      getKiteHandoff(),
    ]);
    savedScreens = screensResult;
    kite = kiteResult;
    watchlists = listsResult.map((list) => ({ id: list.id, name: list.name, colour: list.colour }));
  }
  // A sector column of dashes says nothing (UI audit S3).
  const hasSector = results.some((row) => row.sector);

  // A short result list can go straight to Compare, which takes up to six.
  const compareHref =
    results.length >= 2 && results.length <= 6
      ? buildCompareHref(
          results.map((row) => row.ticker),
          "1Y",
        )
      : null;

  const sortOptions: { key: ScreenerSortKey; label: string }[] = [
    { key: "ticker", label: "Ticker" },
    { key: "price", label: "Price" },
    { key: "rsi", label: "RSI" },
    { key: "trend", label: "vs 200-day" },
    { key: "volatility", label: "Volatility" },
    { key: "pe", label: "P/E" },
    { key: "mcap", label: "Market cap" },
    ...(momentumDays ? [{ key: "momentum" as const, label: `${momentumDays}d %` }] : []),
  ];

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <ResearchPageHeader
        title="Screener"
        description="Screen US and Indian stocks by market, sector, trend, RSI, momentum, volatility and 52-week range. Filters combine with AND logic."
      />

      <div className="mt-5 grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-7">
        <div className="space-y-4">
          <form
            method="GET"
            action="/screener"
            className="space-y-4 rounded-md border border-border-muted bg-card p-4 text-sm"
          >
            {/* Applying filters keeps the chosen sort. */}
            {params.sort ? <input type="hidden" name="sort" value={sort} /> : null}
            {params.sort ? <input type="hidden" name="dir" value={dir} /> : null}
            {/* Applying filters keeps the rule (A2.2). */}
            {rule ? <input type="hidden" name="rule" value={rule} /> : null}
            {rule && ruleMode === "all" ? (
              <input type="hidden" name="rule_mode" value="all" />
            ) : null}
            <div className="flex items-start justify-between gap-3 border-b border-border-muted pb-3">
              <div>
                <p className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
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
              <Label htmlFor="market">Market</Label>
              <select
                id="market"
                name="market"
                defaultValue={params.market ?? ""}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
              >
                <option value="">All markets</option>
                {Object.entries(MARKET_LABEL).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
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
              <summary className="cursor-pointer list-none text-xs font-semibold tracking-[0.02em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
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
              <summary className="cursor-pointer list-none text-xs font-semibold tracking-[0.02em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
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
              <summary className="cursor-pointer list-none text-xs font-semibold tracking-[0.02em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
                Fundamentals
              </summary>
              <fieldset className="mt-2 grid grid-cols-2 gap-2">
                <legend className="sr-only">Fundamentals</legend>
                {(
                  [
                    ["pe_max", "Max P/E", "1"],
                    ["dividend_yield_min", "Min yield %", "0.1"],
                    ["mcap_min_bn", "Min cap, USD bn", "1"],
                    ["roe_min", "Min ROE %", "1"],
                    ["de_max", "Max debt/equity", "0.1"],
                  ] as const
                ).map(([name, label, step]) => (
                  <Input
                    key={name}
                    type="number"
                    name={name}
                    aria-label={label}
                    placeholder={label}
                    step={step}
                    defaultValue={params[name] ?? ""}
                  />
                ))}
                <p className="col-span-2 text-xs text-muted-foreground">
                  As known on the latest close. Market cap is in USD so both markets compare.
                </p>
              </fieldset>
            </details>

            <details className="group rounded-md border border-border-muted/70 px-3 py-2 lg:border-0 lg:px-0 lg:py-0">
              <summary className="cursor-pointer list-none text-xs font-semibold tracking-[0.02em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
                Trend and Volatility
              </summary>
              <fieldset className="mt-2 space-y-2">
                <legend className="sr-only">Trend and volatility</legend>
                {(
                  [
                    ["above_sma_50", "50-day average"],
                    ["above_sma_200", "200-day average"],
                  ] as const
                ).map(([name, label]) => (
                  <div key={name} className="space-y-1">
                    <Label htmlFor={name} className="text-xs">
                      Close vs {label}
                    </Label>
                    <select
                      id={name}
                      name={name}
                      defaultValue={params[name] ?? ""}
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
                    >
                      <option value="">Either</option>
                      <option value="true">Above</option>
                      <option value="false">Below</option>
                    </select>
                  </div>
                ))}
                <Input
                  type="number"
                  name="hv_max"
                  aria-label="Maximum 20-day volatility percent"
                  placeholder="Max volatility %"
                  min={0}
                  step="1"
                  defaultValue={params.hv_max ?? ""}
                />
                <p className="text-xs text-muted-foreground">
                  Volatility is the annualised 20-day historical volatility.
                </p>
              </fieldset>
            </details>

            <details className="group rounded-md border border-border-muted/70 px-3 py-2 lg:border-0 lg:px-0 lg:py-0">
              <summary className="cursor-pointer list-none text-xs font-semibold tracking-[0.02em] text-text-secondary marker:hidden [&::-webkit-details-marker]:hidden">
                52-Week Range
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
          {/* Outside the filter form: SavedScreens holds forms of its own,
              and a form inside a form is invalid HTML (UI audit: it threw a
              hydration error on every screener load). */}
          {signedIn ? (
            <div className="rounded-md border border-border-muted bg-card p-4 text-sm">
              <SavedScreens screens={savedScreens} query={savedScreenQuery(params)} />
            </div>
          ) : (
            <p className="rounded-md border border-border-muted bg-card p-4 text-xs text-text-tertiary">
              <Link href="/login?callbackUrl=/screener" className="underline">
                Sign in
              </Link>{" "}
              to save screens.
            </p>
          )}
        </div>

        <section>
          <RulePanel
            rule={rule ?? ""}
            mode={ruleMode}
            carried={carriedFields(params, ["rule", "rule_mode"])}
            presets={presets}
            signedIn={signedIn}
            clearHref={rule ? clearRuleHref(params) : null}
            aiModel={aiModel}
            draft={draftRuleAction}
          />
          <div className="mb-3 grid gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span className="text-text-secondary">
                {errorMessage
                  ? `Error: ${errorMessage}`
                  : `${total} match${total === 1 ? "" : "es"}${
                      pageCount > 1 ? ` · page ${pageNumber} of ${pageCount}` : ""
                    }`}
                {ruleRun ? (
                  <span className="block text-xs text-text-tertiary" data-testid="rule-counts">
                    Rule on {ruleRun.evaluated} filtered symbol
                    {ruleRun.evaluated === 1 ? "" : "s"}: {ruleRun.counts.met} met,{" "}
                    {ruleRun.counts.not_met} not met, {ruleRun.counts.unknown} unknown
                    {Object.keys(ruleRun.sessions).length
                      ? ` · judged on ${Object.entries(ruleRun.sessions)
                          .map(([venue, day]) => `${formatCloseDate(day)} (${venue})`)
                          .join(", ")}`
                      : ""}
                    .{" "}
                    <Link
                      href={ruleModeHref(params, ruleMode === "all" ? "met_only" : "all")}
                      className="underline"
                    >
                      {ruleMode === "all" ? "Show met only" : "Show all with result"}
                    </Link>
                  </span>
                ) : null}
              </span>
              <span className="flex items-center gap-3 text-xs">
                {activeFilterCount ? null : <span className="text-text-tertiary">All symbols</span>}
                {compareHref ? (
                  <Link
                    href={compareHref}
                    className="inline-flex min-h-8 items-center rounded-full border border-border-muted px-3 text-foreground transition-colors hover:bg-surface-hover"
                  >
                    Compare these {results.length}
                  </Link>
                ) : null}
              </span>
            </div>
            {chips.length ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <ul aria-label="Active filters" className="flex flex-wrap gap-1.5">
                  {chips.map((chip) => (
                    <li key={chip.id}>
                      <Link
                        href={chip.removeHref}
                        aria-label={`Remove filter: ${chip.label}`}
                        className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-border-muted bg-surface-secondary py-1 pr-2 pl-3 text-xs text-foreground transition-colors hover:border-border hover:bg-surface-hover"
                      >
                        {chip.label}
                        <X className="size-3.5 text-text-tertiary" aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
                {chips.length > 1 ? (
                  <Link
                    href={clearFiltersHref(params)}
                    className="px-2 text-xs text-text-secondary hover:text-foreground hover:underline"
                  >
                    Clear all
                  </Link>
                ) : null}
              </div>
            ) : null}
          </div>

          {results.length === 0 && !errorMessage ? (
            <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
              {ruleRun
                ? "No symbol met the rule on its latest session. Show all rows to see each result and why a symbol is unknown."
                : "No symbols match the current filters. Try widening the RSI band or removing the 52-week constraint."}
            </p>
          ) : (
            <>
              {/* Cards below lg, table above — see the markets page for why
                  the switch is lg rather than md. */}
              <div className="mb-3 lg:hidden">
                <CardSortBar
                  options={sortOptions.map((option) => ({
                    ...option,
                    href: screenerSortHref(option.key, params),
                  }))}
                  activeKey={sort}
                  direction={dir}
                />
              </div>
              {signedIn ? (
                <div className="mb-3 lg:hidden">
                  <BulkAddToWatchlist
                    lists={watchlists}
                    mode="all"
                    tickers={results.map((row) => row.ticker)}
                  />
                </div>
              ) : null}
              <SymbolCardList
                className="lg:hidden"
                rows={results.map(
                  (row): SymbolCardData => ({
                    ticker: row.ticker,
                    name: row.name,
                    // In the symbol's own currency, not a hard-coded "$".
                    price: formatCurrency(row.last_close ?? null, row.currency),
                    changePct: momentumDays ? (row.momentum_pct ?? null) : null,
                    changeLabel:
                      momentumDays && row.momentum_pct != null
                        ? `${fmtPct(row.momentum_pct)} · ${momentumDays}d`
                        : null,
                    metrics: [
                      {
                        label: "Close",
                        value: formatCloseDate(row.as_of) ?? "Date unknown",
                      },
                      {
                        label: "RSI 14",
                        value: row.rsi_14 == null ? "—" : row.rsi_14.toFixed(1),
                      },
                      {
                        label: "Market",
                        value: row.market ? (MARKET_LABEL[row.market] ?? row.market) : "—",
                      },
                      {
                        label: "vs 200-day",
                        value: fmtPct(row.sma_200_gap_pct ?? null),
                      },
                      {
                        label: "52w Low",
                        value: formatCurrency(row.low_52w ?? null, row.currency),
                      },
                      {
                        label: "52w High",
                        value: formatCurrency(row.high_52w ?? null, row.currency),
                      },
                      ...(ruleRun && row.rule_result
                        ? [
                            {
                              label: "Rule",
                              value: row.rule_reason
                                ? `${RULE_RESULT_LABEL[row.rule_result]}: ${row.rule_reason}`
                                : RULE_RESULT_LABEL[row.rule_result],
                            },
                          ]
                        : []),
                    ],
                  }),
                )}
              />

              <form
                method="GET"
                action="/compare"
                className="hidden lg:block"
                aria-label="Compare selected symbols"
              >
                <input type="hidden" name="tf" value="1Y" />
                <div className="mb-2 flex flex-wrap items-center justify-between gap-3 text-xs text-text-secondary">
                  <span>
                    Tick up to six rows, then compare them on one shared window
                    {signedIn ? ", or add any number to a watchlist" : ""}.
                  </span>
                  <span className="flex flex-wrap items-center gap-3">
                    {signedIn ? <BulkAddToWatchlist lists={watchlists} mode="selected" /> : null}
                    <Button type="submit" size="sm" variant="outline">
                      Compare selected
                    </Button>
                  </span>
                </div>
                <DataTableFrame>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-8">
                          <span className="sr-only">Select to Compare</span>
                        </TableHead>
                        <SortableHead
                          href={screenerSortHref("ticker", params)}
                          label="Ticker"
                          direction={direction("ticker")}
                          className="w-[110px]"
                        />
                        <TableHead>Name</TableHead>
                        <TableHead>Market</TableHead>
                        {hasSector ? (
                          <TableHead className="hidden 2xl:table-cell">Sector</TableHead>
                        ) : null}
                        <SortableHead
                          href={screenerSortHref("price", params)}
                          label="Price"
                          direction={direction("price")}
                          align="right"
                        />
                        <SortableHead
                          href={screenerSortHref("rsi", params)}
                          label="RSI(14)"
                          direction={direction("rsi")}
                          align="right"
                        />
                        <SortableHead
                          href={screenerSortHref("trend", params)}
                          label="vs 200-day"
                          direction={direction("trend")}
                          align="right"
                        />
                        <SortableHead
                          href={screenerSortHref("volatility", params)}
                          label="Volatility"
                          direction={direction("volatility")}
                          align="right"
                        />
                        <SortableHead
                          href={screenerSortHref("pe", params)}
                          label="P/E"
                          direction={direction("pe")}
                          align="right"
                        />
                        <SortableHead
                          href={screenerSortHref("mcap", params)}
                          label="Mkt cap (USD)"
                          direction={direction("mcap")}
                          align="right"
                        />
                        {/* Momentum exists only for a chosen window; without one
                          the column was a dash on every row (UI audit UX-1). */}
                        {momentumDays ? (
                          <SortableHead
                            href={screenerSortHref("momentum", params)}
                            label={`${momentumDays}d %`}
                            direction={direction("momentum")}
                            align="right"
                          />
                        ) : null}
                        <TableHead className="hidden xl:table-cell">52-Week Range</TableHead>
                        {ruleRun ? <TableHead>Rule</TableHead> : null}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((row) => (
                        <ClickableRow key={row.ticker} href={`/stocks/${row.ticker}`}>
                          <TableCell>
                            <input
                              type="checkbox"
                              name="tickers"
                              value={row.ticker}
                              aria-label={`Compare ${row.ticker}`}
                              className="h-4 w-4 accent-brand"
                            />
                          </TableCell>
                          <TableCell className="ticker font-semibold">{row.ticker}</TableCell>
                          <TableCell className="truncate">{row.name}</TableCell>
                          <TableCell className="text-xs text-text-secondary">
                            {row.mic ?? row.market ?? "—"}
                          </TableCell>
                          {hasSector ? (
                            <TableCell className="hidden text-text-tertiary 2xl:table-cell">
                              {row.sector ?? "—"}
                            </TableCell>
                          ) : null}
                          <NumericCell>
                            {formatCurrency(row.last_close ?? null, row.currency)}
                            <span className="block text-2xs text-text-tertiary">
                              {formatCloseDate(row.as_of)}
                            </span>
                          </NumericCell>
                          <NumericCell>
                            {row.rsi_14 == null ? null : row.rsi_14.toFixed(1)}
                          </NumericCell>
                          <NumericCell signedBy={row.sma_200_gap_pct ?? null}>
                            {row.sma_200_gap_pct == null ? null : fmtPct(row.sma_200_gap_pct)}
                          </NumericCell>
                          <NumericCell>
                            {row.hv_20 == null ? null : `${row.hv_20.toFixed(1)}%`}
                          </NumericCell>
                          <NumericCell>
                            {row.pe == null ? null : `${row.pe.toFixed(1)}×`}
                          </NumericCell>
                          <NumericCell>{formatCompactUsd(row.market_cap_usd ?? null)}</NumericCell>
                          {momentumDays ? (
                            <NumericCell signedBy={row.momentum_pct ?? null}>
                              {row.momentum_pct == null ? null : fmtPct(row.momentum_pct)}
                            </NumericCell>
                          ) : null}
                          <TableCell className="hidden xl:table-cell">
                            <ScreenerRange row={row} />
                          </TableCell>
                          {ruleRun ? (
                            <TableCell className="max-w-[220px]">
                              <RuleResult row={row} />
                            </TableCell>
                          ) : null}
                        </ClickableRow>
                      ))}
                    </TableBody>
                  </Table>
                </DataTableFrame>
              </form>
              {pageCount > 1 ? (
                <nav aria-label="Screener pages" className="mt-3 flex items-center gap-3 text-sm">
                  {pageNumber > 1 ? (
                    <Link href={screenerPageHref(params, pageNumber - 1)} className="underline">
                      Previous
                    </Link>
                  ) : null}
                  <span className="text-text-tertiary">
                    Page {pageNumber} of {pageCount}
                  </span>
                  {pageNumber < pageCount ? (
                    <Link href={screenerPageHref(params, pageNumber + 1)} className="underline">
                      Next
                    </Link>
                  ) : null}
                </nav>
              ) : null}
            </>
          )}
          {signedIn && results.length > 0 ? (
            <ScreenBasket tickers={results.map((row) => row.ticker)} kite={kite} />
          ) : null}
          <UniverseNote universe={screen?.universe ?? null} className="mt-4" />
        </section>
      </div>
    </div>
  );
}

/** A row's rule result (A2.2): met, not met, or unknown with why. */
function RuleResult({ row }: { row: ScreenerRow }) {
  if (!row.rule_result) return <span className="text-text-tertiary">—</span>;
  const tone =
    row.rule_result === "met"
      ? "text-positive"
      : row.rule_result === "unknown"
        ? "text-warning"
        : "text-text-secondary";
  return (
    <span className="block text-xs">
      <span className={`font-medium ${tone}`}>{RULE_RESULT_LABEL[row.rule_result]}</span>
      {row.rule_reason ? (
        <span className="block truncate text-2xs text-text-tertiary" title={row.rule_reason}>
          {row.rule_reason}
        </span>
      ) : null}
    </span>
  );
}

/** The 52-week low and high as one bar with the last close marked on it. */
function ScreenerRange({
  row,
}: {
  row: ScreenerRow;
}) {
  // rangePositionPct returns null for a malformed figure (NaN) or a flat range.
  const position = rangePositionPct(
    Number(row.last_close),
    Number(row.low_52w),
    Number(row.high_52w),
  );
  const lowLabel = formatCurrency(row.low_52w ?? null, row.currency);
  const highLabel = formatCurrency(row.high_52w ?? null, row.currency);
  return (
    <RangeBar
      positionPct={position}
      low={lowLabel}
      high={highLabel}
      label={
        position === null
          ? "52-week range unavailable"
          : `52-week range ${lowLabel} to ${highLabel}; last close ${position.toFixed(0)}% of the way up`
      }
    />
  );
}
