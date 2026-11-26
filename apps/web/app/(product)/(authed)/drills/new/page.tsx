/**
 * /drills/new — launch a deck (A4.7). Prefilled from the entry points through
 * the query string (`drillLaunchHref`): `rule` or `setup_version_id`, and
 * `market`, `tickers` or `watchlist_id`, plus `from`/`to`.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { DrillLaunchForm } from "@/components/drills/drill-launch-form";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import type { StrategySetupOption } from "@/components/rule-strategy/rule-field";
import { listPresets } from "@/lib/api/setups";
import { listSetups } from "@/lib/api/setups-server";
import { listWatchlists } from "@/lib/api/watchlist";

export const metadata: Metadata = { title: "New drill deck" };

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default async function NewDrillDeckPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const q = await searchParams;
  const [presets, own, lists] = await Promise.all([
    listPresets().catch(() => []),
    listSetups().catch(() => []),
    listWatchlists().catch(() => []),
  ]);
  const seen = new Set<number>();
  const setups: StrategySetupOption[] = [];
  for (const s of [...own, ...presets]) {
    const v = s.latest_version;
    if (!v || seen.has(v.id)) continue;
    seen.add(v.id);
    setups.push({ versionId: v.id, name: s.name, rule: v.rule_text, preset: s.is_preset });
  }
  const versionId = Number(q.setup_version_id);
  const watchlistId = q.watchlist_id && /^\d+$/.test(q.watchlist_id) ? q.watchlist_id : "";
  const universe = watchlistId ? "watchlist" : q.tickers ? "tickers" : "market";

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        title="New drill deck"
        description="Practise a setup on its real historical triggers, one replay at a time."
        actions={
          <Link
            href="/drills"
            className="text-sm text-text-secondary underline-offset-4 hover:underline"
          >
            All decks
          </Link>
        }
      />
      <ResearchSubnav current="/drills" />
      <div className="mt-6">
        <DrillLaunchForm
          initial={{
            rule: q.rule ?? "",
            setupVersionId: Number.isInteger(versionId) && versionId > 0 ? versionId : null,
            universe,
            market: q.market === "IN" ? "IN" : "US",
            tickers: q.tickers ?? "",
            watchlistId,
            from: q.from && DATE.test(q.from) ? q.from : "",
            to: q.to && DATE.test(q.to) ? q.to : "",
          }}
          setups={setups}
          watchlists={lists.map((w) => ({ id: w.id, name: w.name, count: w.item_count }))}
        />
      </div>
    </PageFrame>
  );
}
