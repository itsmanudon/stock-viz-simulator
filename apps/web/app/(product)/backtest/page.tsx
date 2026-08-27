/**
 * /backtest — replay a trading strategy over stored historical bars.
 *
 * Server component: fetches the symbol universe, then hands off to the client
 * island that POSTs to /v1/backtest. `?ticker=` prefills the experiment.
 */

import { BacktestForm } from "@/components/backtest-form";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { listSymbols } from "@/lib/api";

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const { ticker: rawTicker } = await searchParams;
  const symbols = await listSymbols();
  const options = [...symbols]
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }));
  const initialTicker = rawTicker?.trim().toUpperCase();

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        title="Backtest"
        description="Test deterministic trading rules on stored daily bars. Results are a historical what-if, not live trading and not a market-microstructure simulation."
      />
      <ResearchSubnav current="/backtest" />
      <BacktestForm symbols={options} initialTicker={initialTicker} />
    </PageFrame>
  );
}
