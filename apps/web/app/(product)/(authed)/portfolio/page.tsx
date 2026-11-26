import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import { loadBookContext } from "@/lib/book-context";
import { currentMonthKey, parseMonthKey } from "@/lib/journal-view-model";
import { loadPortfolioData } from "@/lib/portfolio-data";
import { parsePortfolioRange, parsePortfolioTab } from "@/lib/portfolio-view-model";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Portfolio" };

type Params = { range?: string; tab?: string; month?: string; goal?: string; book?: string };

export default async function PortfolioPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  // A5.2: `?book=<id|all>`; absent is the default book (lib/book-url.ts).
  const books = await loadBookContext(params.book, "/portfolio", params);
  const range = parsePortfolioRange(params.range);
  const tab = parsePortfolioTab(params.tab);
  // The Journal's month is server-rendered so the calendar arrives with data.
  // Later month changes are client-side; see components/journal/journal-panel.
  const monthKey = parseMonthKey(params.month, currentMonthKey());
  const data = await loadPortfolioData(range, tab === "journal" ? monthKey : undefined, {
    news: tab === "news",
    risk: tab === "analytics",
    options: tab === "options",
    goal: parseGoal(params.goal),
    book: books.book,
  });

  return (
    <PortfolioWorkspace
      {...data}
      range={range}
      tab={tab}
      journalMonthKey={monthKey}
      goal={parseGoal(params.goal)}
      bookContext={{ book: books.book, selected: books.selected, isAll: books.isAll }}
    />
  );
}

/** Phase 8.6: a target value from `?goal=`, positive and finite, else none. */
function parseGoal(raw: string | undefined): number | null {
  const value = Number(raw);
  return raw && Number.isFinite(value) && value > 0 && value <= 1e12 ? value : null;
}
