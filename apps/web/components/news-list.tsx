import { SentimentBadge } from "@/components/sentiment-badge";
import type { NewsArticle } from "@/lib/api";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * The publisher's date when there is one; otherwise the day Aegis collected
 * it, labelled as such (audit AG-12: GDELT sends no publish time).
 */
export function newsDateLabel(article: NewsArticle): string {
  if (article.published_at) return formatCloseDate(article.published_at) ?? "";
  const collected = formatCloseDate(article.available_at);
  return collected ? `Collected ${collected}` : "";
}

export function NewsList({
  articles,
  variant = "cards",
}: {
  articles: NewsArticle[];
  variant?: "cards" | "workspace";
}) {
  if (articles.length === 0) {
    return (
      <p
        className={
          variant === "workspace"
            ? "border-y border-border-muted py-6 text-sm text-muted-foreground"
            : "rounded-md border border-border-muted bg-card p-5 text-sm text-muted-foreground"
        }
      >
        {/* Written for readers: the old copy named an environment variable
            (UI audit S1). */}
        {variant === "workspace"
          ? "No stored headlines for this symbol yet. News is collected once a day."
          : "No stored headlines yet. News is collected once a day; check back tomorrow."}
      </p>
    );
  }

  return (
    <ul className={variant === "workspace" ? "divide-y divide-border-muted" : "space-y-3"}>
      {articles.map((article) => (
        <li
          key={article.id}
          className={
            variant === "workspace"
              ? "transition-colors hover:bg-surface-hover/60"
              : "rounded-md border border-border-muted bg-card p-4 transition hover:bg-accent"
          }
        >
          <ArticleLink url={article.url}>
            <div className={variant === "workspace" ? "py-4" : ""}>
              <div className="flex items-baseline justify-between gap-4">
                <h3 className="font-medium leading-6">{article.title}</h3>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {newsDateLabel(article)}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <SentimentBadge sentiment={article.sentiment} />
                <span>{article.source}</span>
                {variant === "cards" && article.tickers.length > 0 ? (
                  <span className="font-mono">{article.tickers.join(" · ")}</span>
                ) : null}
              </div>
            </div>
          </ArticleLink>
        </li>
      ))}
    </ul>
  );
}

/** A document without a link still lists, as plain text. */
function ArticleLink({ url, children }: { url: string | null; children: React.ReactNode }) {
  if (!url) return <div className="block">{children}</div>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="block">
      {children}
    </a>
  );
}
