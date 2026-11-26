import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { ChecklistPanel } from "@/components/checklist/checklist-panel";
import {
  ContextualTradeTicket,
  type TicketPosition,
  type TradeTicketAccount,
} from "@/components/contextual-trade-ticket";
import { ChartWorkbench } from "@/components/drawings/chart-workbench";
import { NewsReactions } from "@/components/event-study-view";
import { FundamentalsPanel } from "@/components/fundamentals-panel";
import { MobileTradeSheet } from "@/components/mobile-trade-sheet";
import { NewsList } from "@/components/news-list";
import { PositionSummary } from "@/components/position-summary";
import { PriceChart } from "@/components/price-chart";
import { RelativeStrengthStrip } from "@/components/relative-strength-strip";
import { SecurityHeader } from "@/components/security-header";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import { StockMetricsStrip } from "@/components/stock-metrics-strip";
import { StockResearchTabs } from "@/components/stock-research-tabs";
import { TickerOrders } from "@/components/ticker-orders";
import type { TicketBook } from "@/components/ticket-book-line";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import {
  ApiError,
  type SymbolChecklist,
  type SymbolDetail,
  getBars,
  getIndicatorCatalog,
  getIndicators,
  getNewsForTicker,
  getSymbol,
} from "@/lib/api";
import { listBooks } from "@/lib/api/books";
import {
  type Delivery,
  type RelativeStrength,
  getDelivery,
  getRelativeStrength,
  getSymbolEvents,
} from "@/lib/api/chart-context";
import { getSymbolChecklist } from "@/lib/api/checklist";
import { listDrawings } from "@/lib/api/drawings";
import { getMyFills } from "@/lib/api/events-server";
import { getFundamentals, getValuation, getValuationHistory } from "@/lib/api/fundamentals";
import { getEventStudy } from "@/lib/api/research";
import {
  type PendingOrder,
  type Portfolio,
  type Position,
  getPortfolio,
  listOrders,
} from "@/lib/api/trading";
import type { Indicators } from "@/lib/api/types";
import { type WatchlistList, listWatchlists } from "@/lib/api/watchlist";
import { type ChartEvent, eventBarIndex, mergeEvents, resolveEventTypes } from "@/lib/chart-events";
import { parseChartView } from "@/lib/chart-view";
import { barDate } from "@/lib/drawings/anchor";
import type { DrawingsResponse } from "@/lib/drawings/kinds";
import { badgesFor } from "@/lib/indicator-badge";
import {
  type ChartPane,
  STOCK_TIMEFRAMES,
  type StockIndicator,
  type StockTimeframe,
  barsForLookback,
  buildStockChartHref,
  calculateAllocationPct,
  calculatePeriodReturnPct,
  calculatePositionReturnPct,
  chartLayers,
  deriveTrailingBarMetrics,
  formatCloseDate,
  macdSeries,
  parseStockIndicators,
  parseStockInterval,
  studyFor,
} from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";
import { checkVisitorLimit } from "@/lib/visitor-limit";

const TIMEFRAME_DAYS: Record<StockTimeframe, number> = {
  "1M": 22,
  "3M": 65,
  "6M": 130,
  "1Y": 252,
  "5Y": 1260,
  MAX: 5000,
};

function parseTimeframe(raw: string | undefined): StockTimeframe {
  return STOCK_TIMEFRAMES.includes(raw as StockTimeframe) ? (raw as StockTimeframe) : "1Y";
}

function ticketPosition(position: Position, portfolio: Portfolio): TicketPosition {
  const quantity = Number(position.quantity);
  const averageCost = Number(position.avg_cost);
  const unrealizedNative = Number(position.unrealized_pl_native);
  return {
    quantity,
    availableQuantity: Number(position.available_quantity),
    averageCost,
    marketValue: Number(position.market_value),
    unrealizedPnl: Number(position.unrealized_pl),
    returnPct: calculatePositionReturnPct(unrealizedNative, averageCost * quantity),
    allocationPct: calculateAllocationPct(
      Number(position.market_value),
      Number(portfolio.total_value),
    ),
  };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ ticker: string }>;
}): Promise<Metadata> {
  // The ticker alone: the company name would cost an API call per render.
  return { title: decodeURIComponent((await params).ticker).toUpperCase() };
}

export default async function StockPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{
    tf?: string;
    indicators?: string;
    interval?: string;
    type?: string;
    scale?: string;
    adjustment?: string;
    events?: string;
  }>;
}) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  const visitorLimit = await checkVisitorLimit("stock");
  if (!visitorLimit.allowed) {
    return <VisitorLimitNotice retryAfterSeconds={visitorLimit.retryAfterSeconds} />;
  }
  const ticker = rawTicker.toUpperCase();
  const timeframe = parseTimeframe(query.tf);
  // A3.4: the catalog's parameter bounds validate the URL's keys (a failed
  // call keeps the studies at most at their parameter count, unbounded).
  const catalog = await getIndicatorCatalog().catch(() => null);
  const selectedIndicators = parseStockIndicators(
    query.indicators,
    catalog ? Object.fromEntries(catalog.map((c) => [c.key, c.parameters])) : null,
  );
  const timeframeDays = TIMEFRAME_DAYS[timeframe];
  // A1.4a: the bar interval (daily, weekly, monthly) is separate from the
  // lookback; the limit counts bars of that interval.
  const interval = parseStockInterval(query.interval);
  const chartLimit = barsForLookback(timeframeDays, interval);

  let symbol: SymbolDetail;
  try {
    symbol = await getSymbol(ticker);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // A3.1: raw prices only where the API stores them; otherwise adjusted.
  const requestedView = parseChartView(query);
  const hasRaw = Boolean(symbol.has_raw);
  const view =
    requestedView.adjustment === "raw" && !hasRaw
      ? { ...requestedView, adjustment: "adjusted" as const }
      : requestedView;
  const rawRequestedButMissing = requestedView.adjustment === "raw" && !hasRaw;

  const barsPromise = getBars(ticker, { interval, limit: chartLimit });
  // The header's period return and the metrics stay on adjusted prices.
  const chartBarsPromise =
    view.adjustment === "raw"
      ? getBars(ticker, { interval, limit: chartLimit, adjustment: "raw" }).catch(() => null)
      : barsPromise;
  // The metrics strip (52-week range, daily RSI) always reads daily bars.
  const rangeBarsPromise =
    interval === "1d" && timeframeDays >= 252 ? barsPromise : getBars(ticker, { limit: 252 });
  const requestedIndicators = Array.from(new Set([...selectedIndicators, "rsi_14"]));
  // Chart indicators run on the chart's own bars (weekly RSI on weekly bars).
  const indicatorsPromise = getIndicators(ticker, {
    names: requestedIndicators,
    interval,
    limit: chartLimit,
  }).catch(() => ({ ticker, series: {}, macd: null, meta: {} }) as Indicators);
  const dailyRsiPromise =
    interval === "1d"
      ? indicatorsPromise
      : getIndicators(ticker, { names: ["rsi_14"], limit: 22 }).catch(() => null);

  const [
    bars,
    rawChartBars,
    rangeBars,
    indicatorBundle,
    dailyRsiBundle,
    news,
    session,
    fundamentalsAnnual,
    fundamentalsQuarterly,
    valuationNow,
    peHistory,
    negativeReactions,
    positiveReactions,
    checklist,
    relativeStrength,
  ] = await Promise.all([
    barsPromise,
    chartBarsPromise,
    rangeBarsPromise,
    indicatorsPromise,
    dailyRsiPromise,
    getNewsForTicker(ticker, 8).catch(() => []),
    auth(),
    // Phase 6.4: a failing financials call hides the panel, never the page.
    getFundamentals(ticker, "annual").catch(() => null),
    getFundamentals(ticker, "quarter").catch(() => null),
    getValuation(ticker).catch(() => null),
    getValuationHistory(ticker, "pe").catch(() => null),
    // Phase 7.4: how this stock moved around its negative and positive news.
    getEventStudy({ tickers: [ticker], sentiment: "negative" }).catch(() => null),
    getEventStudy({ tickers: [ticker], sentiment: "positive" }).catch(() => null),
    // A2.4: the six-dimension checklist; a failed call drops the panel only.
    getSymbolChecklist(ticker).catch(() => null),
    // A3.5: RS percentiles and the 52-week distance; a failed call drops the strip.
    getRelativeStrength(ticker).catch(() => null as RelativeStrength | null),
  ]);

  const signedIn = Boolean(session?.user?.id);

  // A3.5: chart events over the chart's range (to today, so a headline after
  // the last bar is still listed), the viewer's own fills, and delivery %.
  const eventTypes = resolveEventTypes(view.events, signedIn);
  const chartRange = bars.length
    ? { from: barDate(bars[0].ts), to: new Date().toISOString().slice(0, 10) }
    : null;
  const [publicEvents, fills, delivery] = await Promise.all([
    chartRange && eventTypes.some((t) => t !== "fill")
      ? getSymbolEvents(ticker, chartRange).catch(() => null)
      : Promise.resolve(null),
    chartRange && signedIn && eventTypes.includes("fill")
      ? getMyFills(ticker, chartRange).catch(() => null)
      : Promise.resolve(null),
    symbol.is_indian
      ? getDelivery(ticker, interval, chartRange?.from).catch(() => null as Delivery | null)
      : Promise.resolve(null),
  ]);
  const chartEvents: ChartEvent[] | undefined = chartRange
    ? mergeEvents([publicEvents?.events, fills], eventTypes)
    : undefined;
  let portfolio: Portfolio | null = null;
  let tickerOrders: PendingOrder[] | null = null;
  let inWatchlist = false;
  let watchlists: WatchlistList[] = [];
  let drawings: DrawingsResponse | null = null;
  // A5.2: this ticket trades into the default book, and says so.
  let ticketBook: TicketBook | null = null;

  if (signedIn) {
    const [portfolioResult, ordersResult, watchlistResult, drawingsResult, booksResult] =
      await Promise.all([
        getPortfolio().catch(() => null),
        listOrders("pending").catch(() => null),
        // A2.5: every list, each saying whether it holds this ticker.
        listWatchlists(ticker).catch(() => [] as WatchlistList[]),
        // A3.2: the user's drawings; a failed call turns the tools off, not the chart.
        listDrawings(ticker).catch(() => null),
        listBooks().catch(() => null),
      ]);
    const defaultBook = booksResult?.books.find((b) => b.is_default) ?? null;
    ticketBook = defaultBook
      ? { id: defaultBook.id, name: defaultBook.name, currency: defaultBook.base_currency }
      : null;
    drawings = drawingsResult;
    portfolio = portfolioResult;
    tickerOrders = ordersResult?.filter((order) => order.ticker === ticker) ?? null;
    watchlists = watchlistResult;
    inWatchlist = watchlistResult.some((list) => list.is_default && list.contains);
  }

  const rawPosition = portfolio?.positions.find((position) => position.ticker === ticker) ?? null;
  const position = rawPosition && portfolio ? ticketPosition(rawPosition, portfolio) : null;
  const account: TradeTicketAccount | null = portfolio
    ? {
        displayCurrency: portfolio.display_currency,
        availableCash: Number(portfolio.available_cash),
        position,
      }
    : null;
  const positionStatus = !signedIn
    ? "sign-in"
    : !portfolio
      ? "unavailable"
      : position
        ? "held"
        : "not-held";

  const latestClose = symbol.latest ? Number(symbol.latest.close) : null;
  const firstClose = bars[0] ? Number(bars[0].close) : null;
  const periodReturnPct = calculatePeriodReturnPct(firstClose, latestClose);
  const metrics = deriveTrailingBarMetrics(rangeBars);
  // A3.4: the first RSI and MACD on the chart get their own panes, whatever
  // their parameters; another instance draws in a pane of its own.
  const rsiKey = selectedIndicators.find((k) => studyFor(k)?.key === "rsi");
  const macdKey = selectedIndicators.find((k) => studyFor(k)?.key === "macd");
  const rsiSeries = rsiKey ? indicatorBundle.series[rsiKey] : undefined;
  const macdPoints = macdKey ? macdSeries(indicatorBundle, macdKey) : null;
  const badges = badgesFor(selectedIndicators, catalog);
  const latestRsi = dailyRsiBundle?.series.rsi_14?.at(-1)?.value ?? null;
  const partialExcluded =
    interval !== "1d" && selectedIndicators.length > 0 && indicatorBundle.partial_bar_excluded;
  // Phase 6.6: overlays and panes by each indicator's registry pane.
  const { overlays: overlaySeries, panes: studyPanes } = chartLayers(
    indicatorBundle,
    selectedIndicators,
    [rsiKey, macdKey],
  );
  // A3.5: the RS line names its index; without index closes it says so.
  const benchmarkLabel = symbol.benchmark
    ? `${symbol.benchmark_name ?? symbol.benchmark} (${symbol.benchmark})`
    : "its index";
  const rsEmpty =
    studyPanes.some(
      (p) => studyFor(p.name)?.key === "rsline" && Object.values(p.lines).every((l) => !l.length),
    ) ||
    (selectedIndicators.some((k) => studyFor(k)?.key === "rsline") &&
      !studyPanes.some((p) => studyFor(p.name)?.key === "rsline"));
  const indicatorPanes = studyPanes.map((p) =>
    studyFor(p.name)?.key === "rsline" ? { ...p, label: `RS line vs ${benchmarkLabel}` } : p,
  );
  // A3.5: delivery % and its 20-day average, mounted by default on NSE/BSE charts.
  const deliveryPane = deliveryChartPane(delivery, bars, interval);
  if (deliveryPane) indicatorPanes.push(deliveryPane);
  const deliveryEmpty = symbol.is_indian && !deliveryPane;
  // A raw request that failed falls back to the adjusted bars, and says so.
  const rawFailed = view.adjustment === "raw" && rawChartBars === null;
  const showingRaw = view.adjustment === "raw" && rawChartBars !== null;
  const chartBars = showingRaw ? rawChartBars : bars;
  const activeStockUrl = buildStockChartHref(ticker, timeframe, selectedIndicators, interval, view);
  const ticketProps = {
    book: ticketBook,
    ticker,
    name: symbol.name,
    currency: symbol.currency,
    latestClose,
    closeDate: symbol.latest?.ts ?? null,
    signedIn,
    account,
    callbackUrl: activeStockUrl,
    openOrderCount: tickerOrders?.length ?? (signedIn ? null : 0),
  };

  return (
    // Bottom padding on narrow screens keeps the pinned Buy/Sell bar from
    // covering the last section.
    <div className="px-4 pt-5 pb-32 sm:px-6 sm:pt-6 lg:px-8 lg:pt-7 xl:pb-7">
      <SecurityHeader
        symbol={symbol}
        latestClose={latestClose}
        periodReturnPct={periodReturnPct}
        timeframe={timeframe}
        periodStart={bars[0]?.ts ?? null}
        signedIn={signedIn}
        inWatchlist={inWatchlist}
        watchlists={watchlists}
        hasPosition={position !== null}
        callbackUrl={activeStockUrl}
      />

      <MobileTradeSheet {...ticketProps} />

      <div className="mt-5 grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_19.5rem] xl:items-start xl:gap-6">
        <div className="min-w-0 space-y-4">
          <section
            aria-label={`${ticker} price chart`}
            className="overflow-hidden rounded-md border border-border-muted bg-card"
          >
            <StockChartToolbar
              ticker={ticker}
              timeframe={timeframe}
              indicators={selectedIndicators}
              interval={interval}
              view={showingRaw ? view : { ...view, adjustment: "adjusted" }}
              hasRaw={hasRaw}
              catalog={catalog}
              signedIn={signedIn}
            />
            <div className="p-1.5 sm:p-3">
              {chartBars.length && !showingRaw ? (
                <ChartWorkbench
                  ticker={ticker}
                  signedIn={signedIn}
                  initial={drawings}
                  callbackUrl={activeStockUrl}
                  bars={chartBars}
                  overlays={overlaySeries}
                  macd={macdPoints}
                  rsi={rsiSeries ?? null}
                  rsiKey={rsiKey}
                  macdKey={macdKey}
                  badges={badges}
                  panes={indicatorPanes}
                  interval={interval}
                  chartType={view.type}
                  scale={view.scale}
                  events={chartEvents}
                  currency={symbol.currency}
                />
              ) : chartBars.length ? (
                <PriceChart
                  bars={chartBars}
                  // Overlays and drawings are on adjusted prices: on raw
                  // prices they would jump at every split, so they are left off.
                  overlays={{}}
                  macd={macdPoints}
                  rsi={rsiSeries ?? null}
                  rsiKey={rsiKey}
                  macdKey={macdKey}
                  badges={badges}
                  panes={indicatorPanes}
                  interval={interval}
                  chartType={view.type}
                  scale={view.scale}
                  events={chartEvents}
                  currency={symbol.currency}
                />
              ) : (
                <p className="py-24 text-center text-sm text-muted-foreground">
                  No price history is available for this timeframe.
                </p>
              )}
              {deliveryEmpty ? (
                <div
                  className="mx-1 mt-2 flex items-baseline gap-2 rounded-sm border border-dashed border-border-muted px-3 py-2 text-2xs"
                  data-testid="delivery-empty"
                >
                  <span className="font-medium text-text-secondary">Delivery %</span>
                  <span className="text-text-tertiary">
                    {delivery === null
                      ? "Delivery figures could not be loaded."
                      : "No delivery data yet. NSE delivery files have not been loaded for this symbol."}
                  </span>
                </div>
              ) : null}
              {rsEmpty ? (
                <p className="px-1 pt-1 text-2xs text-text-tertiary" data-testid="rs-empty">
                  The RS line divides the close by {benchmarkLabel}; no closes of that index are
                  stored yet, so it is not drawn.
                </p>
              ) : null}
              {showingRaw ? (
                <p className="px-1 pt-1 text-2xs text-text-tertiary" data-testid="raw-prices-note">
                  Raw exchange prices, as published, not adjusted for splits. Indicators and
                  drawings are on adjusted prices, so price overlays and drawings are hidden here.
                </p>
              ) : null}
              {rawRequestedButMissing || rawFailed ? (
                <p className="px-1 pt-1 text-2xs text-text-tertiary">
                  {rawRequestedButMissing
                    ? "Only adjusted prices are stored for this symbol, so the chart shows those."
                    : "Raw prices could not be loaded, so the chart shows adjusted prices."}
                </p>
              ) : null}
              {partialExcluded ? (
                <p className="px-1 pt-1 text-2xs text-text-tertiary">
                  Indicators run on {interval === "1wk" ? "weekly" : "monthly"} bars and leave out
                  the partial {interval === "1wk" ? "week" : "month"} until it closes.
                </p>
              ) : null}
            </div>
          </section>

          <StockMetricsStrip
            metrics={metrics}
            currency={symbol.currency}
            rsi={latestRsi}
            latestClose={latestClose}
          />
          {relativeStrength ? <RelativeStrengthStrip strength={relativeStrength} /> : null}
        </div>

        <aside
          aria-label={`Paper trade ${ticker}`}
          className="sticky top-[4.5rem] hidden max-h-[calc(100dvh-5.5rem)] overflow-y-auto rounded-md border border-border-muted bg-surface-elevated p-4 xl:block"
        >
          <ContextualTradeTicket {...ticketProps} />
        </aside>
      </div>

      <section aria-label={`${ticker} research`} className="mt-7 xl:mt-8">
        <StockResearchTabs
          newsCount={news.length}
          orderCount={tickerOrders?.length ?? 0}
          overview={
            <Overview
              symbol={symbol}
              latestTimestamp={metrics.latestTimestamp}
              positionStatus={positionStatus}
              checklist={checklist}
            />
          }
          financials={
            <FundamentalsPanel
              annual={fundamentalsAnnual}
              quarterly={fundamentalsQuarterly}
              valuation={valuationNow}
              peHistory={peHistory}
            />
          }
          news={
            <div className="space-y-8">
              <NewsList articles={news} variant="workspace" />
              <NewsReactions
                ticker={ticker}
                negative={negativeReactions}
                positive={positiveReactions}
              />
            </div>
          }
          positionOrders={
            signedIn ? (
              <div className="space-y-8">
                {!portfolio ? (
                  <div className="border-y border-border-muted py-6">
                    <h3 className="text-base font-semibold">Portfolio context unavailable</h3>
                    <p className="mt-1 text-sm text-warning">
                      StockViz could not verify your current position or buying power. No holding
                      status is being inferred.
                    </p>
                  </div>
                ) : position ? (
                  <PositionSummary
                    ticker={ticker}
                    nativeCurrency={symbol.currency}
                    displayCurrency={portfolio?.display_currency ?? symbol.currency}
                    position={position}
                  />
                ) : (
                  <div className="border-y border-border-muted py-6">
                    <h3 className="text-base font-semibold">No current position</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      You do not currently hold {ticker}. Your research and open orders remain
                      available here.
                    </p>
                  </div>
                )}
                <TickerOrders ticker={ticker} currency={symbol.currency} orders={tickerOrders} />
              </div>
            ) : (
              <GuestPersonalContext ticker={ticker} callbackUrl={activeStockUrl} />
            )
          }
        />
      </section>
    </div>
  );
}

/** Delivery points placed on the chart's bars (the events' period rule), or null with none. */
function deliveryChartPane(
  delivery: Delivery | null,
  bars: { ts: string }[],
  interval: "1d" | "1wk" | "1mo",
): ChartPane | null {
  if (!delivery?.has_data || !delivery.points.length || !bars.length) return null;
  const dates = bars.map((b) => barDate(b.ts));
  const pct = new Map<string, number>();
  const avg = new Map<string, number>();
  for (const point of delivery.points) {
    const index = eventBarIndex(point.ts, interval, dates);
    if (index === null) continue;
    const ts = bars[index].ts;
    pct.set(ts, point.delivery_pct);
    if (point.avg_20 !== null && point.avg_20 !== undefined) avg.set(ts, point.avg_20);
  }
  if (!pct.size) return null;
  return {
    name: "delivery",
    label: "Delivery %",
    lines: {
      delivery: [...pct].map(([ts, value]) => ({ ts, value })),
      "delivery.avg_20": [...avg].map(([ts, value]) => ({ ts, value })),
    },
    outputLabels: { delivery: "Delivery %", "delivery.avg_20": "20-day avg" },
  };
}

function Overview({
  symbol,
  latestTimestamp,
  positionStatus,
  checklist,
}: {
  checklist?: SymbolChecklist | null;
  symbol: SymbolDetail;
  latestTimestamp: string | null;
  positionStatus: "held" | "not-held" | "sign-in" | "unavailable";
}) {
  const items = [
    ["Ticker", symbol.ticker],
    // "Not recorded" rather than a dash: the value exists, we just have not
    // loaded it (`stockviz.cli metadata`; UI audit S3).
    ["Exchange", symbol.exchange ?? "Not recorded"],
    ["Sector", symbol.sector ?? "Not recorded"],
    ["Trading currency", symbol.currency],
  ];

  return (
    <div className="space-y-8">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.55fr)]">
        <div>
          <p className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
            Security Overview
          </p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">{symbol.name}</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Price history, technical analysis, company news, and paper-trading context are organized
            around this security. Market orders use the latest cached close as their simulation
            basis.
          </p>
          <p className="mt-3 text-xs leading-5 text-text-tertiary">
            End-of-day data
            {latestTimestamp
              ? ` through ${formatCloseDate(latestTimestamp) ?? latestTimestamp}`
              : ""}
            . The indicative price is simulated from the cached close and is not a realtime market
            quote.
          </p>
          <nav aria-label="Research this security" className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link href={`/compare?tickers=${symbol.ticker}`} className="hover:underline">
              Compare
            </Link>
            <Link
              href={`/backtest?ticker=${symbol.ticker}`}
              className="text-text-secondary hover:underline"
            >
              Backtest
            </Link>
            <Link
              href={`/checklist?q=${symbol.ticker}`}
              className="text-text-secondary hover:underline"
            >
              Checklist
            </Link>
          </nav>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-y border-border-muted py-5">
          {items.map(([label, value]) => (
            <div key={label}>
              <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                {titleCase(label)}
              </dt>
              <dd className="mt-1 text-sm font-medium">{value}</dd>
            </div>
          ))}
          <div>
            <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
              Portfolio Status
            </dt>
            <dd className="mt-1 text-sm font-medium">
              {positionStatus === "held"
                ? "Current holding"
                : positionStatus === "not-held"
                  ? "Not held"
                  : positionStatus === "sign-in"
                    ? "Sign in to view"
                    : "Unavailable"}
            </dd>
          </div>
        </dl>
      </div>
      {checklist ? <ChecklistPanel checklist={checklist} /> : null}
    </div>
  );
}

function GuestPersonalContext({ ticker, callbackUrl }: { ticker: string; callbackUrl: string }) {
  return (
    <div className="border-y border-border-muted py-7">
      <h3 className="text-base font-semibold">Your position and orders</h3>
      <p className="mt-1.5 max-w-xl text-sm leading-6 text-muted-foreground">
        Sign in to see whether you hold {ticker}, review reserved shares and buying power, and
        manage pending paper orders.
      </p>
      <Link
        href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
        className="mt-4 inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Sign in
      </Link>
    </div>
  );
}
