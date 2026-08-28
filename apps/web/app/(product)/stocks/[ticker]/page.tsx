import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { CommentsSection } from "@/components/comments-section";
import {
  ContextualTradeTicket,
  type TicketPosition,
  type TradeTicketAccount,
} from "@/components/contextual-trade-ticket";
import { MobileTradeSheet } from "@/components/mobile-trade-sheet";
import { NewsList } from "@/components/news-list";
import { PositionSummary } from "@/components/position-summary";
import { PriceChart } from "@/components/price-chart";
import { SecurityHeader } from "@/components/security-header";
import { StockChartToolbar } from "@/components/stock-chart-toolbar";
import { StockMetricsStrip } from "@/components/stock-metrics-strip";
import { StockResearchTabs } from "@/components/stock-research-tabs";
import { TickerOrders } from "@/components/ticker-orders";
import {
  ApiError,
  type SymbolDetail,
  getBars,
  getIndicators,
  getNewsForTicker,
  getSymbol,
} from "@/lib/api";
import { listComments } from "@/lib/api/comments";
import {
  type PendingOrder,
  type Portfolio,
  type Position,
  getPortfolio,
  listOrders,
} from "@/lib/api/trading";
import { listWatchlist } from "@/lib/api/watchlist";
import {
  STOCK_TIMEFRAMES,
  type StockIndicator,
  type StockTimeframe,
  buildStockChartHref,
  calculateAllocationPct,
  calculatePeriodReturnPct,
  calculatePositionReturnPct,
  deriveTrailingBarMetrics,
  parseStockIndicators,
} from "@/lib/stock-workspace";

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

export default async function StockPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ tf?: string; indicators?: string }>;
}) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  const ticker = rawTicker.toUpperCase();
  const timeframe = parseTimeframe(query.tf);
  const selectedIndicators = parseStockIndicators(query.indicators);
  const timeframeDays = TIMEFRAME_DAYS[timeframe];

  let symbol: SymbolDetail;
  try {
    symbol = await getSymbol(ticker);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const barsPromise = getBars(ticker, { limit: timeframeDays });
  const rangeBarsPromise = timeframeDays >= 252 ? barsPromise : getBars(ticker, { limit: 252 });
  const requestedIndicators = Array.from(new Set([...selectedIndicators, "rsi_14"]));

  const [bars, rangeBars, indicatorBundle, news, session, comments] = await Promise.all([
    barsPromise,
    rangeBarsPromise,
    getIndicators(ticker, { names: requestedIndicators, limit: timeframeDays }),
    getNewsForTicker(ticker, 8).catch(() => []),
    auth(),
    listComments(ticker).catch(() => [] as Awaited<ReturnType<typeof listComments>>),
  ]);

  const signedIn = Boolean(session?.user?.id);
  const currentUserId = session?.user?.id ? Number(session.user.id) : null;
  let portfolio: Portfolio | null = null;
  let tickerOrders: PendingOrder[] | null = null;
  let inWatchlist = false;

  if (signedIn) {
    const [portfolioResult, ordersResult, watchlistResult] = await Promise.all([
      getPortfolio().catch(() => null),
      listOrders("pending").catch(() => null),
      listWatchlist().catch(() => []),
    ]);
    portfolio = portfolioResult;
    tickerOrders = ordersResult?.filter((order) => order.ticker === ticker) ?? null;
    inWatchlist = watchlistResult.some((item) => item.ticker === ticker);
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
  const rsiSeries = indicatorBundle.series.rsi_14;
  const latestRsi = rsiSeries?.at(-1)?.value ?? null;
  const overlaySeries = Object.fromEntries(
    Object.entries(indicatorBundle.series).filter(
      ([name]) => name !== "rsi_14" && selectedIndicators.includes(name as StockIndicator),
    ),
  );
  const showMacd = selectedIndicators.includes("macd");
  const validCurrentUserId = Number.isFinite(currentUserId) ? currentUserId : null;
  const activeStockUrl = buildStockChartHref(ticker, timeframe, selectedIndicators);
  const ticketProps = {
    ticker,
    name: symbol.name,
    currency: symbol.currency,
    latestClose,
    signedIn,
    account,
    callbackUrl: activeStockUrl,
    openOrderCount: tickerOrders?.length ?? (signedIn ? null : 0),
  };

  return (
    <div className="px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
      <SecurityHeader
        symbol={symbol}
        latestClose={latestClose}
        periodReturnPct={periodReturnPct}
        timeframe={timeframe}
        signedIn={signedIn}
        inWatchlist={inWatchlist}
        hasPosition={position !== null}
        callbackUrl={activeStockUrl}
      />

      <div className="mt-4 xl:hidden">
        <MobileTradeSheet {...ticketProps} />
      </div>

      <div className="mt-6 grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_20.5rem] xl:items-start">
        <div className="min-w-0 space-y-5">
          <section
            aria-label={`${ticker} price chart`}
            className="overflow-hidden border-y border-border-muted bg-surface-elevated sm:border-x"
          >
            <StockChartToolbar
              ticker={ticker}
              timeframe={timeframe}
              indicators={selectedIndicators}
            />
            <div className="p-2 sm:p-4">
              {bars.length ? (
                <PriceChart
                  bars={bars}
                  overlays={overlaySeries}
                  macd={showMacd ? indicatorBundle.macd : null}
                />
              ) : (
                <p className="py-24 text-center text-sm text-muted-foreground">
                  No price history is available for this timeframe.
                </p>
              )}
            </div>
          </section>

          <StockMetricsStrip metrics={metrics} currency={symbol.currency} rsi={latestRsi} />
        </div>

        <aside
          aria-label={`Paper trade ${ticker}`}
          className="sticky top-17 hidden max-h-[calc(100dvh-5rem)] overflow-y-auto border border-border-muted bg-surface-elevated p-5 xl:block"
        >
          <ContextualTradeTicket {...ticketProps} />
        </aside>
      </div>

      <section aria-label={`${ticker} research`} className="mt-8">
        <StockResearchTabs
          newsCount={news.length}
          orderCount={tickerOrders?.length ?? 0}
          overview={
            <Overview
              symbol={symbol}
              latestTimestamp={metrics.latestTimestamp}
              positionStatus={positionStatus}
            />
          }
          news={<NewsList articles={news} variant="workspace" />}
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
          discussion={
            <CommentsSection
              ticker={ticker}
              comments={comments}
              currentUserId={validCurrentUserId}
              embedded
            />
          }
        />
      </section>
    </div>
  );
}

function Overview({
  symbol,
  latestTimestamp,
  positionStatus,
}: {
  symbol: SymbolDetail;
  latestTimestamp: string | null;
  positionStatus: "held" | "not-held" | "sign-in" | "unavailable";
}) {
  const items = [
    ["Ticker", symbol.ticker],
    ["Exchange", symbol.exchange ?? "—"],
    ["Sector", symbol.sector ?? "—"],
    ["Trading currency", symbol.currency],
  ];

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.55fr)]">
      <div>
        <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-text-tertiary">
          Security overview
        </p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight">{symbol.name}</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          Price history, technical analysis, company news, and paper-trading context are organized
          around this security. Market orders use the latest cached close as their simulation basis.
        </p>
        <p className="mt-3 text-xs leading-5 text-text-tertiary">
          End-of-day data{latestTimestamp ? ` through ${latestTimestamp}` : ""}. The indicative
          price is simulated from the cached close and is not a realtime market quote.
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
            href={`/recommendations?q=${symbol.ticker}`}
            className="text-text-secondary hover:underline"
          >
            Signals
          </Link>
        </nav>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-y border-border-muted py-5">
        {items.map(([label, value]) => (
          <div key={label}>
            <dt className="text-3xs font-semibold uppercase tracking-[0.12em] text-text-tertiary">
              {label}
            </dt>
            <dd className="mt-1 text-sm font-medium">{value}</dd>
          </div>
        ))}
        <div>
          <dt className="text-3xs font-semibold uppercase tracking-[0.12em] text-text-tertiary">
            Portfolio status
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
