/**
 * /trade — paper execution workstation.
 *
 * Server component: loads the symbol universe, portfolio, pending orders,
 * recent fills, and the selected ticker's stored close in parallel. The
 * ticket is a client island. `/trade?ticker=` is the shareable symbol.
 */

import Link from "next/link";

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
import { ApiError, getQuotes, listSymbols } from "@/lib/api";
import { getPortfolio, listOrders, listTrades } from "@/lib/api/trading";
import { currencyByTicker, parseTradeTicker } from "@/lib/operational-trading";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default async function TradePage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const { ticker: rawTicker } = await searchParams;
  const requestedTicker = parseTradeTicker(rawTicker);

  const [symbols, portfolio, pendingOrders, recentTrades] = await Promise.all([
    listSymbols(),
    getPortfolio(),
    listOrders("pending"),
    listTrades(8),
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

  const quote = activeTicker
    ? await getQuotes([activeTicker]).catch((err) => {
        if (err instanceof ApiError) return [];
        throw err;
      })
    : [];
  const selectedQuote = quote[0] ?? null;
  const position = portfolio.positions.find((item) => item.ticker === activeTicker) ?? null;
  const tickerOrders = pendingOrders.filter((order) => order.ticker === activeTicker);
  const currencies = currencyByTicker(options);

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
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
        <div className="mt-6 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,20rem)] lg:items-start">
          {/* Unkeyed: a fill revalidates this page and must not remount the ticket. */}
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
          />

          <aside className="space-y-8">
            <section
              aria-labelledby="account-context-heading"
              className="border-y border-border-muted sm:border-x"
            >
              <div className="border-b border-border-muted px-4 py-3">
                <h2 id="account-context-heading" className="text-sm font-semibold">
                  Account context
                </h2>
                <p className="mt-1 text-xs leading-5 text-text-tertiary">
                  Cash and shares after pending reservations. Source: current portfolio snapshot.
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-px bg-border-muted">
                <div className="bg-background px-4 py-3">
                  <dt className="text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                    Buying power
                  </dt>
                  <dd className="mt-1 font-mono text-lg tabular-nums">
                    {formatCurrency(portfolio.available_cash, portfolio.display_currency)}
                  </dd>
                </div>
                <div className="bg-background px-4 py-3">
                  <dt className="text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                    Cash
                  </dt>
                  <dd className="mt-1 font-mono text-lg tabular-nums">
                    {formatCurrency(portfolio.cash_balance, portfolio.display_currency)}
                  </dd>
                </div>
                <div className="bg-background px-4 py-3">
                  <dt className="text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                    Reserved
                  </dt>
                  <dd className="mt-1 font-mono text-lg tabular-nums">
                    {formatCurrency(portfolio.reserved_cash, portfolio.display_currency)}
                  </dd>
                </div>
                <div className="bg-background px-4 py-3">
                  <dt className="text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                    Total value
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
      )}

      <section aria-labelledby="recent-activity-heading" className="mt-10">
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
          <p className="mt-4 border-y border-border-muted py-6 text-sm text-text-secondary">
            No fills yet. Submit a market order to see it here and in Portfolio.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto border-y border-border-muted">
            <table className="w-full min-w-[36rem] text-sm">
              <caption className="sr-only">Recent paper fills</caption>
              <thead>
                <tr className="border-b border-border-muted text-left text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                  <th scope="col" className="px-3 py-2.5">
                    When
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
                    <td className="px-3 py-2.5 font-mono">
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

      <section aria-labelledby="options-ticket-heading" className="mt-10">
        <h2 id="options-ticket-heading" className="text-sm font-semibold">
          Options
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-5 text-text-tertiary">
          Buy calls and puts to open. Premiums use Black-Scholes with 30-day historical volatility,
          not a live implied-vol surface. Close positions from{" "}
          <Link href="/portfolio?tab=options" className="hover:underline">
            Portfolio
          </Link>
          .
        </p>
        <div className="mt-4 max-w-xl">
          <OptionTradeForm
            options={options.map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }))}
          />
        </div>
      </section>
    </PageFrame>
  );
}
