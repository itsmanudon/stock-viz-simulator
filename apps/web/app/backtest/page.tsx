/**
 * /backtest — replay a trading strategy over stored historical bars.
 *
 * Server component: fetches the symbol universe for the form dropdown, then
 * hands off to the client-side BacktestForm which POSTs to /v1/backtest and
 * renders the equity curve, trade log, and summary stats.
 */

import { BacktestForm } from "@/components/backtest-form";
import { listSymbols } from "@/lib/api";

export default async function BacktestPage() {
  const symbols = await listSymbols();
  const options = [...symbols]
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((s) => ({ ticker: s.ticker, name: s.name }));

  return (
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Backtest</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Replay a strategy over stored daily bars. Signals are all-in / all-out; results use only
          historical data — no live trading.
        </p>
      </header>

      <BacktestForm symbols={options} />
    </div>
  );
}
