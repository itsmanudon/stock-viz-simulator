import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import { currentMonthKey, parseMonthKey } from "@/lib/journal-view-model";
import { loadPortfolioData } from "@/lib/portfolio-data";
import { parsePortfolioRange, parsePortfolioTab } from "@/lib/portfolio-view-model";

export default async function PortfolioPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; tab?: string; month?: string }>;
}) {
  const params = await searchParams;
  const range = parsePortfolioRange(params.range);
  const tab = parsePortfolioTab(params.tab);
  // The Journal's month is server-rendered so the calendar arrives with data.
  // Later month changes are client-side; see components/journal/journal-panel.
  const monthKey = parseMonthKey(params.month, currentMonthKey());
  const data = await loadPortfolioData(range, tab === "journal" ? monthKey : undefined);

  return <PortfolioWorkspace {...data} range={range} tab={tab} journalMonthKey={monthKey} />;
}
