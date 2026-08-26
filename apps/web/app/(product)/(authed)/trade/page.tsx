/**
 * /trade — paper-trading order ticket.
 *
 * Server component for the symbol dropdown + portfolio preview; the form
 * itself is the client TradeForm below. POST flows through the server action
 * in ./actions.ts which calls /v1/trades.
 */

import Link from "next/link";

import { OptionTradeForm } from "@/components/option-trade-form";
import { TradeForm } from "@/components/trade-form";
import { Card, CardContent } from "@/components/ui/card";
import { listSymbols } from "@/lib/api";
import { getPortfolio } from "@/lib/api/trading";

function fmtCurrency(raw: string | null): string {
  if (raw === null) return "—";
  const n = Number(raw);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

export default async function TradePage() {
  const [symbols, portfolio] = await Promise.all([listSymbols(), getPortfolio()]);

  // Sort tickers; positions go first so selling is fast.
  const heldTickers = new Set(portfolio.positions.map((p) => p.ticker));
  const options = [...symbols].sort((a, b) => {
    const aHeld = heldTickers.has(a.ticker);
    const bHeld = heldTickers.has(b.ticker);
    if (aHeld !== bHeld) return aHeld ? -1 : 1;
    return a.ticker.localeCompare(b.ticker);
  });

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Place a trade</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Market orders fill at the most recent EOD close.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TradeForm
            options={options.map((s) => ({
              ticker: s.ticker,
              name: s.name,
              currency: s.currency || "USD",
            }))}
            heldTickers={Array.from(heldTickers)}
          />
        </div>

        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 text-sm font-medium text-muted-foreground">Buying power</h2>
            <p className="font-mono text-2xl">{fmtCurrency(portfolio.available_cash)}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Cash {fmtCurrency(portfolio.cash_balance)}
              {Number(portfolio.reserved_cash) > 0
                ? ` · Reserved ${fmtCurrency(portfolio.reserved_cash)}`
                : ""}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Total value {fmtCurrency(portfolio.total_value)}
            </p>
            {portfolio.positions.length > 0 ? (
              <div className="mt-6">
                <h3 className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                  Currently holding
                </h3>
                <ul className="space-y-1.5 text-sm">
                  {portfolio.positions.slice(0, 8).map((p) => (
                    <li key={p.ticker} className="flex items-baseline justify-between">
                      <Link href={`/stocks/${p.ticker}`} className="font-mono hover:underline">
                        {p.ticker}
                      </Link>
                      <span className="font-mono text-xs text-muted-foreground">
                        {Number(p.available_quantity).toLocaleString()} avail
                        {Number(p.reserved_quantity) > 0
                          ? ` / ${Number(p.quantity).toLocaleString()} owned`
                          : " sh"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <section className="mt-12">
        <header className="mb-4">
          <h2 className="text-2xl font-bold tracking-tight">Options</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Buy calls and puts to open. Premiums use Black-Scholes with 30-day historical
            volatility, not a live implied-vol surface. Manage and close positions from the{" "}
            <Link href="/portfolio" className="text-foreground underline">
              portfolio page
            </Link>
            .
          </p>
        </header>
        <div className="lg:max-w-2xl">
          <OptionTradeForm options={options.map((s) => ({ ticker: s.ticker, name: s.name }))} />
        </div>
      </section>
    </div>
  );
}
