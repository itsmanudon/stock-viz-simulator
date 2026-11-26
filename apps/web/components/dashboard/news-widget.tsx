import { BookLink as Link } from "@/components/book-link";

import { WidgetCard, WidgetEmpty } from "@/components/dashboard/widget-card";
import { newsDateLabel } from "@/components/news-list";
import { SentimentBadge } from "@/components/sentiment-badge";
import type { NewsArticle } from "@/lib/api/types";

/**
 * Headlines about what the account holds or watches: documents Aegis linked to
 * one of `tickers`, newest first. Each row names the symbols it is linked to
 * (only those in `tickers`), its source and its date, and opens the publisher's
 * page when there is one. General market news lives on /news, not here.
 */
export function NewsWidget({
  news,
  tickers,
}: {
  news: NewsArticle[] | null;
  tickers: string[];
}) {
  const mine = new Set(tickers);
  return (
    <WidgetCard
      title="News on your symbols"
      titleId="dashboard-news-heading"
      action={{ label: "All news", href: "/news" }}
    >
      {news === null ? (
        <WidgetEmpty>News is unavailable right now.</WidgetEmpty>
      ) : tickers.length === 0 ? (
        <WidgetEmpty>
          Hold or watch a symbol to see its news here.{" "}
          <Link href="/watchlist" className="font-medium text-brand hover:underline">
            Add to your watchlist
          </Link>
          .
        </WidgetEmpty>
      ) : news.length === 0 ? (
        <WidgetEmpty>
          No stored headlines about your holdings or watchlist yet.{" "}
          <Link href="/news?view=market" className="font-medium text-brand hover:underline">
            Market headlines
          </Link>
          .
        </WidgetEmpty>
      ) : (
        <ul aria-label="Headlines" className="divide-y divide-border-muted">
          {news.map((article) => {
            const linked = article.tickers.filter((t) => mine.has(t.toUpperCase()));
            const date = newsDateLabel(article);
            return (
              <li key={article.id} className="py-2.5 first:pt-0 last:pb-0">
                {article.url ? (
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm leading-5 font-medium hover:underline"
                  >
                    {article.title}
                  </a>
                ) : (
                  <p className="text-sm leading-5 font-medium">{article.title}</p>
                )}
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-text-tertiary">
                  {linked.map((ticker) => (
                    <Link
                      key={ticker}
                      href={`/stocks/${encodeURIComponent(ticker)}`}
                      className="ticker font-semibold text-text-secondary hover:text-foreground"
                    >
                      {ticker}
                    </Link>
                  ))}
                  {article.source ? <span>{article.source}</span> : null}
                  {date ? <span>{date}</span> : null}
                  {article.sentiment ? <SentimentBadge sentiment={article.sentiment} /> : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetCard>
  );
}
