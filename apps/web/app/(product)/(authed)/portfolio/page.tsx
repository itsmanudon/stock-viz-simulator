import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import { loadPortfolioData } from "@/lib/portfolio-data";
import { parsePortfolioRange, parsePortfolioTab } from "@/lib/portfolio-view-model";

export default async function PortfolioPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; tab?: string }>;
}) {
  const params = await searchParams;
  const range = parsePortfolioRange(params.range);
  const tab = parsePortfolioTab(params.tab);
  const data = await loadPortfolioData(range);

  return <PortfolioWorkspace {...data} range={range} tab={tab} />;
}
