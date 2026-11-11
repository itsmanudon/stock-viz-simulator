/**
 * /backtest — replay a trading strategy over stored historical bars.
 *
 * Server component: fetches the symbol universe, then hands off to the client
 * island that POSTs to /v1/backtest. `?ticker=` prefills the experiment.
 */

import { BacktestForm } from "@/components/backtest-form";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { getMarketsSummary, listSymbols } from "@/lib/api";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Backtest" };

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const { ticker: rawTicker } = await searchParams;
  const [symbols, summary] = await Promise.all([
    listSymbols(),
    // Only used to start on a symbol with history (UI audit F1); the page
    // still works without it.
    getMarketsSummary().catch(() => null),
  ]);
  const lastClose = new Map(
    summary?.rows.map((row) => [row.ticker, row.last_close_at?.slice(0, 10) ?? null]) ?? [],
  );
  const options = [...symbols]
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((symbol) => ({
      ticker: symbol.ticker,
      name: symbol.name,
      lastClose: summary ? (lastClose.get(symbol.ticker) ?? null) : undefined,
    }));
  const initialTicker = rawTicker?.trim().toUpperCase();

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="Backtest"
        description="Test deterministic trading rules on stored daily bars. Results are a historical what-if, not live trading and not a market-microstructure simulation."
      />
      <ResearchSubnav current="/backtest" />
      <BacktestForm symbols={options} initialTicker={initialTicker} />
    </PageFrame>
  );
}
