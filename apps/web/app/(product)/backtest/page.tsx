/**
 * /backtest — replay a trading strategy over stored historical bars.
 *
 * Server component: fetches the symbol universe, then hands off to a client
 * island. `?mode=rule` (A4.1) is the Rule strategy mode (Rule DSL entry and
 * exit, stops, sizing, a universe); without it the two templates POST to
 * /v1/backtest from the browser. `?ticker=` prefills either.
 */

import Link from "next/link";

import { auth } from "@/auth";
import { BacktestForm } from "@/components/backtest-form";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import type { StrategySetupOption } from "@/components/rule-strategy/rule-field";
import {
  RuleStrategyForm,
  type StrategyWatchlist,
} from "@/components/rule-strategy/rule-strategy-form";
import { getMarketsSummary, listSymbols } from "@/lib/api";
import { listPresets } from "@/lib/api/setups";
import { listSetups } from "@/lib/api/setups-server";
import { listWatchlists } from "@/lib/api/watchlist";
import { cn } from "@/lib/utils";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Backtest" };

function ModeTabs({ mode, ticker }: { mode: "templates" | "rule"; ticker?: string }) {
  const q = ticker ? `ticker=${encodeURIComponent(ticker)}` : "";
  const tabs = [
    { mode: "templates", label: "Templates", href: `/backtest${q ? `?${q}` : ""}` },
    { mode: "rule", label: "Rule strategy", href: `/backtest?mode=rule${q ? `&${q}` : ""}` },
  ] as const;
  return (
    <nav aria-label="Backtest mode" className="mt-4 flex gap-2" data-testid="backtest-mode">
      {tabs.map((tab) => (
        <Link
          key={tab.mode}
          href={tab.href}
          aria-current={tab.mode === mode ? "page" : undefined}
          className={cn(
            "rounded-full border px-3 py-1 text-sm",
            tab.mode === mode
              ? "border-brand text-foreground"
              : "border-border-muted text-text-secondary hover:text-foreground",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string; mode?: string }>;
}) {
  const { ticker: rawTicker, mode: rawMode } = await searchParams;
  const mode = rawMode === "rule" ? "rule" : "templates";
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

  let ruleProps: {
    setups: StrategySetupOption[];
    watchlists: StrategyWatchlist[];
    signedIn: boolean;
  } | null = null;
  if (mode === "rule") {
    const session = await auth();
    const signedIn = Boolean(session?.user?.id);
    const [presets, own, lists] = await Promise.all([
      listPresets().catch(() => []),
      signedIn ? listSetups().catch(() => []) : Promise.resolve([]),
      signedIn ? listWatchlists().catch(() => []) : Promise.resolve([]),
    ]);
    const seen = new Set<number>();
    const setups: StrategySetupOption[] = [];
    for (const s of [...own, ...presets]) {
      const v = s.latest_version;
      if (!v || seen.has(v.id) || s.kind === "checklist") continue;
      seen.add(v.id);
      setups.push({ versionId: v.id, name: s.name, rule: v.rule_text, preset: s.is_preset });
    }
    ruleProps = {
      setups,
      signedIn,
      watchlists: lists.map((w) => ({ id: w.id, name: w.name, count: w.item_count })),
    };
  }

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="Backtest"
        description="Test deterministic trading rules on stored daily bars. Results are a historical what-if, not live trading and not a market-microstructure simulation."
      />
      <ResearchSubnav current="/backtest" />
      <ModeTabs mode={mode} ticker={initialTicker} />
      {ruleProps ? (
        <RuleStrategyForm symbols={options} initialTicker={initialTicker} {...ruleProps} />
      ) : (
        <BacktestForm symbols={options} initialTicker={initialTicker} />
      )}
    </PageFrame>
  );
}
