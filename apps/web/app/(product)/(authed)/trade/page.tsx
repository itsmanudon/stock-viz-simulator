/**
 * /trade — paper execution workstation.
 *
 * Server component: loads the symbol universe, portfolio, pending orders,
 * recent fills, and the selected ticker's stored close in parallel. The
 * ticket is a client island. `/trade?ticker=` is the shareable symbol.
 */

import { BookLink as Link } from "@/components/book-link";
import type { Metadata } from "next";

import {
  OperationalEmptyState,
  OperationalPageHeader,
  OperationalSubnav,
  OrderSideBadge,
  OrderTypeBadge,
} from "@/components/operational-page-header";
import { OptionTradeForm } from "@/components/option-trade-form";
import { PendingOrderQuote } from "@/components/order-blotter-row";
import { OrderTicket } from "@/components/order-ticket";
import { PageFrame } from "@/components/page-frame";
import { PriceChart } from "@/components/price-chart";
import { StrategyBuilder } from "@/components/strategy-builder";
import { ApiError, getBars, getQuotes, listSymbols } from "@/lib/api";
import { parseApiTimestamp } from "@/lib/api-time";
import { getPortfolio, listOrders, listTrades } from "@/lib/api/trading";
import { loadBookContext } from "@/lib/book-context";
import { currencyByTicker, parseTradeTicker } from "@/lib/operational-trading";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";

export const metadata: Metadata = { title: "Trade" };

/** Fill times are stored in UTC; show them in UTC and say so (audit T4). */
function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return parseApiTimestamp(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export default async function TradePage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; book?: string }>;
}) {
  const params = await searchParams;
  const requestedTicker = parseTradeTicker(params.ticker);
  // A5.2: the ticket trades into `?book=` (default when absent). All books and
  // archived or imported books show the account and disable every ticket.
  const books = await loadBookContext(params.book, "/trade", params);
  const ticketBook =
    books.selected && !books.isAll
      ? {
          id: books.selected.id,
          name: books.selected.name,
          currency: books.selected.base_currency,
        }
      : null;

  const [symbols, portfolio, pendingOrders, recentTrades] = await Promise.all([
    listSymbols(),
    getPortfolio(books.book),
    listOrders("pending", books.book),
    listTrades(8, books.book),
  ]);

  const heldTickers = new Set(portfolio.positions.map((position) => position.ticker));
  const options = [...symbols].sort((a, b) => {
    const aHeld = heldTickers.has(a.ticker);
    const bHeld = heldTickers.has(b.ticker);
    if (aHeld !== bHeld) return aHeld ? -1 : 1;
    return a.ticker.localeCompare(b.ticker);
  });
  const known = new Set(options.map((item) => item.ticker));
  const ticker = requestedTicker && known.has(requestedTicker) ? requestedTicker : "";
  const activeTicker = ticker || options[0]?.ticker || "";

  const [quote, chartBars] = activeTicker
    ? await Promise.all([
        getQuotes([activeTicker]).catch((err) => {
          if (err instanceof ApiError) return [];
          throw err;
        }),
        getBars(activeTicker, { limit: 90 }).catch((err) => {
          if (err instanceof ApiError) return [];
          throw err;
        }),
      ])
    : [[], []];
  const selectedQuote = quote[0] ?? null;
  const position = portfolio.positions.find((item) => item.ticker === activeTicker) ?? null;
  const tickerOrders = pendingOrders.filter((order) => order.ticker === activeTicker);
  const currencies = currencyByTicker(options);

  // The API takes USD stocks only (audit LG-7): no other currency, and no
  // index (^GSPC is USD but has no options here).
  const optionUnderlyings = options
    .filter((symbol) => (symbol.currency || "USD") === "USD" && !symbol.ticker.startsWith("^"))
    .map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }));

  const recentExecution = (
    <section
      aria-labelledby="recent-activity-heading"
      className="order-4 min-w-0 rounded-md border border-border-muted bg-card px-4 py-3.5"
    >
      <h2 id="recent-activity-heading" className="text-sm font-semibold">
        Recent execution
      </h2>
      <p className="mt-1 text-xs text-text-tertiary">
        Latest fills from the trade ledger. Full history lives on{" "}
        <Link href="/trades" className="hover:underline">
          Trade history
        </Link>
        .
      </p>
      {recentTrades.length === 0 ? (
        <p className="mt-3 border-t border-border-muted pt-4 text-sm text-text-secondary">
          No fills yet. Submit a market order to see it here and in Portfolio.
        </p>
      ) : (
        <div className="-mx-4 mt-3 overflow-x-auto border-t border-border-muted">
          <table className="w-full min-w-[36rem] text-sm">
            <caption className="sr-only">Recent paper fills</caption>
            <thead>
              <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                <th scope="col" className="px-3 py-2.5">
                  When (UTC)
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Ticker
                </th>
                <th scope="col" className="px-3 py-2.5">
                  Side
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Qty
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Fill
                </th>
              </tr>
            </thead>
            <tbody>
              {recentTrades.map((trade) => (
                <tr key={trade.id} className="border-b border-border-muted last:border-0">
                  <td className="px-3 py-2.5 text-text-tertiary">{fmtWhen(trade.ts)}</td>
                  <td className="ticker px-3 py-2.5 font-semibold">
                    <Link href={`/stocks/${trade.ticker}`} className="hover:underline">
                      {trade.ticker}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5">
                    <OrderSideBadge side={trade.side} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {formatQuantity(trade.quantity)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {formatCurrency(trade.price, trade.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <OperationalPageHeader
        eyebrow="Trade"
        title="Trade"
        description="Paper execution workstation. Market orders fill at the latest stored daily close. Limit, stop-loss, and take-profit orders wait for that close — they are not live exchange triggers."
        actions={
          <Link href="/orders" className="text-sm hover:underline">
            Open orders
          </Link>
        }
      />
      <OperationalSubnav current="/trade" />

      {options.length === 0 ? (
        <div className="mt-6">
          <OperationalEmptyState
            title="No symbols loaded"
            action={<Link href="/markets">Browse markets</Link>}
          >
            <p>
              The execution ticket needs the tracked universe. Seed or ingest symbols, then return
              here.
            </p>
          </OperationalEmptyState>
        </div>
      ) : (
        // Aurora board v3: chart and recent fills on the left, the ticket and
        // its account on the right. Below xl the column wrappers dissolve
        // (`contents`) and `order-*` keeps chart, ticket, account, fills.
        <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start">
          <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-5">
            <section
              aria-label={`${activeTicker} price context`}
              className="order-1 min-w-0 overflow-hidden rounded-md border border-border-muted bg-card"
            >
              <div className="flex items-center justify-between gap-3 border-b border-border-muted px-4 py-3.5">
                <div>
                  <h2 className="text-sm font-semibold">Price context</h2>
                  <p className="mt-1 text-xs text-text-tertiary">
                    {activeTicker} · last 90 stored end-of-day bars
                  </p>
                </div>
                <Link
                  href={`/stocks/${activeTicker}`}
                  className="text-xs font-medium text-brand hover:underline"
                >
                  Open research
                </Link>
              </div>
              <div className="p-2 sm:p-3">
                {chartBars.length ? (
                  <PriceChart bars={chartBars} />
                ) : (
                  <p className="py-20 text-center text-sm text-text-secondary">
                    No stored price history is available for this symbol.
                  </p>
                )}
              </div>
            </section>
            {recentExecution}
          </div>

          <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-5">
            {/* Unkeyed: a fill revalidates this page and must not remount the ticket. */}
            <div className="order-2 min-w-0">
              <OrderTicket
                symbols={options.map((symbol) => ({
                  ticker: symbol.ticker,
                  name: symbol.name,
                  currency: symbol.currency || "USD",
                }))}
                initialTicker={activeTicker}
                quoteClose={selectedQuote?.close ?? position?.last_close ?? null}
                quoteAt={selectedQuote?.ts ?? null}
                position={
                  position
                    ? {
                        quantity: position.quantity,
                        availableQuantity: position.available_quantity,
                        reservedQuantity: position.reserved_quantity,
                        averageCost: position.avg_cost,
                        lastClose: position.last_close,
                        currency: position.currency,
                      }
                    : null
                }
                availableCash={portfolio.available_cash}
                displayCurrency={portfolio.display_currency || "USD"}
                book={ticketBook}
                blockedReason={books.tradeBlock}
              />
            </div>

            <aside className="order-3 min-w-0 space-y-5">
              <section
                aria-labelledby="account-context-heading"
                className="overflow-hidden rounded-md border border-border-muted bg-card"
              >
                <div className="border-b border-border-muted px-4 py-3.5">
                  <h2 id="account-context-heading" className="text-sm font-semibold">
                    Account
                  </h2>
                  {books.isAll || books.selected ? (
                    <p className="mt-1 text-xs font-medium text-text-secondary">
                      {books.isAll
                        ? "All books, in your display currency"
                        : `Book: ${books.selected?.name}`}
                    </p>
                  ) : null}
                  <p className="mt-1 text-xs leading-5 text-text-tertiary">
                    Cash and shares after pending reservations. Source: current portfolio snapshot.
                  </p>
                </div>
                <dl className="grid grid-cols-2 gap-px bg-border-muted">
                  <div className="bg-background px-4 py-3">
                    <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                      Buying Power
                    </dt>
                    <dd className="mt-1 font-mono text-lg tabular-nums">
                      {formatCurrency(portfolio.available_cash, portfolio.display_currency)}
                    </dd>
                  </div>
                  <div className="bg-background px-4 py-3">
                    <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                      Cash
                    </dt>
                    <dd className="mt-1 font-mono text-lg tabular-nums">
                      {formatCurrency(portfolio.cash_balance, portfolio.display_currency)}
                    </dd>
                  </div>
                  <div className="bg-background px-4 py-3">
                    <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                      Reserved by Orders
                    </dt>
                    <dd className="mt-1 font-mono text-lg tabular-nums">
                      {formatCurrency(portfolio.reserved_cash, portfolio.display_currency)}
                    </dd>
                  </div>
                  <div className="bg-background px-4 py-3">
                    <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
                      Total Value
                    </dt>
                    <dd className="mt-1 font-mono text-lg tabular-nums">
                      {formatCurrency(portfolio.total_value, portfolio.display_currency)}
                    </dd>
                  </div>
                </dl>
                {position ? (
                  <div className="border-t border-border-muted px-4 py-3 text-sm">
                    <p className="font-medium">{activeTicker} position</p>
                    <p className="mt-1 text-xs leading-5 text-text-tertiary">
                      {formatQuantity(position.quantity)} owned ·{" "}
                      {formatQuantity(position.available_quantity)} available · avg{" "}
                      {formatCurrency(position.avg_cost, position.currency)}
                    </p>
                  </div>
                ) : (
                  <p className="border-t border-border-muted px-4 py-3 text-xs text-text-tertiary">
                    No open stock position in {activeTicker || "this symbol"}.
                  </p>
                )}
                {tickerOrders.length > 0 ? (
                  <ul className="border-t border-border-muted divide-y divide-border-muted">
                    {tickerOrders.map((order) => (
                      <li
                        key={order.id}
                        className="flex items-center justify-between gap-2 px-4 py-2 text-xs"
                      >
                        <span className="flex items-center gap-2">
                          <OrderSideBadge side={order.side} />
                          <OrderTypeBadge type={order.order_type} />
                          <PendingOrderQuote order={order} currencies={currencies} />
                        </span>
                        <Link href="/orders" className="hover:underline">
                          Manage
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="border-t border-border-muted px-4 py-3 text-xs text-text-tertiary">
                    No pending orders for {activeTicker || "this symbol"}.
                  </p>
                )}
              </section>
            </aside>
          </div>
        </div>
      )}

      {options.length === 0 ? recentExecution : null}

      <section aria-labelledby="options-ticket-heading" className="mt-8">
        <h2 id="options-ticket-heading" className="text-sm font-semibold">
          Options
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-5 text-text-tertiary">
          Buy or write single contracts, or open a strategy whose legs open together. Premiums use
          Black-Scholes on a stored option chain&apos;s implied volatility where there is one, else
          30-day historical volatility; they are not market quotes. Close positions from{" "}
          <Link href="/portfolio?tab=options" className="hover:underline">
            Portfolio
          </Link>
          .
        </p>
        <div className="mt-4 grid gap-6 xl:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-medium text-text-secondary">One contract type</h3>
            <OptionTradeForm
              options={optionUnderlyings}
              book={ticketBook}
              blockedReason={books.tradeBlock}
            />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-medium text-text-secondary">Strategy builder</h3>
            <StrategyBuilder
              options={optionUnderlyings}
              book={ticketBook}
              blockedReason={books.tradeBlock}
            />
          </div>
        </div>
      </section>
    </PageFrame>
  );
}
