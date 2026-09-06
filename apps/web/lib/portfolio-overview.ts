import "server-only";

import { getPortfolio, getPortfolioOverview } from "@/lib/api/trading";

/** One valuation on success, with the required portfolio still available if analytics fail. */
export async function loadPortfolioOverview() {
  try {
    return await getPortfolioOverview();
  } catch {
    return { portfolio: await getPortfolio(), analytics: null };
  }
}
