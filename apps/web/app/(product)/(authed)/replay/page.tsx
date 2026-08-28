/**
 * /replay — Replay Lab launcher.
 *
 * Authenticated. Lists isolated historical sessions and opens a new frozen
 * 1d range. Live paper Portfolio is never touched.
 */

import { PageFrame } from "@/components/page-frame";
import { ReplayLauncher } from "@/components/replay-launcher";
import { ReplaySessionTable } from "@/components/replay-session-list";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { listSymbols } from "@/lib/api";
import { listReplaySessions } from "@/lib/api/replay";

export default async function ReplayPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const { ticker: rawTicker } = await searchParams;
  const [symbols, sessions] = await Promise.all([listSymbols(), listReplaySessions()]);
  const options = [...symbols]
    .filter((symbol) => (symbol.currency || "USD") === "USD")
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map((symbol) => ({ ticker: symbol.ticker, name: symbol.name }));
  const initialTicker = rawTicker?.trim().toUpperCase();

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        title="Replay"
        description="Stand on a historical replay date. You will not see what happens next. Trades fill at the stored daily close on an isolated replay book."
      />
      <ResearchSubnav current="/replay" />
      <div className="mt-6 space-y-8">
        <ReplayLauncher symbols={options} initialTicker={initialTicker} />
        <ReplaySessionTable sessions={sessions} />
      </div>
    </PageFrame>
  );
}
