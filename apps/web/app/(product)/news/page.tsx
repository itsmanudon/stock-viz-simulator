/**
 * /news — paginated news feed pulled from /v1/news.
 *
 * Page size is fixed; ``?page=N`` advances. The API caps ``limit`` at 100;
 * we ask for ``PAGE_SIZE + 1`` so we know whether there's a next page
 * without a separate count query.
 */

import Link from "next/link";

import { NewsList } from "@/components/news-list";
import { getLatestNews } from "@/lib/api";

const PAGE_SIZE = 25;

export default async function NewsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const { page: rawPage } = await searchParams;
  const page = Math.max(1, Number.parseInt(rawPage ?? "1", 10) || 1);
  const skip = (page - 1) * PAGE_SIZE;

  // We can't directly skip on the API, so fetch ``page * size + 1`` and slice.
  // For Phase 5 with 25 tickers and an empty news table this is plenty; if the
  // feed ever gets large we'll add an ``?offset`` param.
  const wanted = page * PAGE_SIZE + 1;
  const raw = await getLatestNews(Math.min(wanted, 100)).catch(
    () => [] as Awaited<ReturnType<typeof getLatestNews>>,
  );
  const slice = raw.slice(skip, skip + PAGE_SIZE);
  const hasNext = raw.length > skip + PAGE_SIZE;

  return (
    <div className="container mx-auto px-4 py-6 sm:px-6 lg:py-7">
      <header className="mb-5">
        <p className="text-2xs font-semibold tracking-[0.14em] text-brand uppercase">Research</p>
        <h1 className="mt-1.5 text-3xl font-semibold tracking-tight">News</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Latest market news ingested from newsdata.io.
        </p>
      </header>

      <NewsList articles={slice} />

      <nav className="mt-6 flex items-center justify-between text-sm text-muted-foreground">
        <span>Page {page}</span>
        <div className="flex gap-3">
          {page > 1 ? (
            <Link
              href={`/news?page=${page - 1}`}
              className="rounded-md border px-3 py-1.5 hover:bg-accent hover:text-foreground"
            >
              ← Previous
            </Link>
          ) : null}
          {hasNext ? (
            <Link
              href={`/news?page=${page + 1}`}
              className="rounded-md border px-3 py-1.5 hover:bg-accent hover:text-foreground"
            >
              Next →
            </Link>
          ) : null}
        </div>
      </nav>
    </div>
  );
}
