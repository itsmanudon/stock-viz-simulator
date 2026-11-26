import "server-only";

import { getPortfolio, getPortfolioOverview } from "@/lib/api/trading";
import type { BookRef } from "@/lib/book-url";

/** One valuation on success, with the required portfolio still available if analytics fail. */
export async function loadPortfolioOverview(book: BookRef | null = null) {
  try {
    return await getPortfolioOverview(book);
  } catch {
    return { portfolio: await getPortfolio(book), analytics: null };
  }
}
