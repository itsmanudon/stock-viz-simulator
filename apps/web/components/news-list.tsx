import { SentimentBadge } from "@/components/sentiment-badge";
import type { NewsArticle } from "@/lib/api";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function NewsList({ articles }: { articles: NewsArticle[] }) {
  if (articles.length === 0) {
    return (
      <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
        No recent news. The news ingest runs every 4 hours when a NEWSDATA_KEY is configured.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {articles.map((article) => (
        <li key={article.id} className="rounded-lg border bg-card p-4 transition hover:bg-accent">
          <a href={article.url} target="_blank" rel="noopener noreferrer" className="block">
            <div className="flex items-baseline justify-between gap-4">
              <h3 className="font-medium">{article.title}</h3>
              <span className="shrink-0 text-xs text-muted-foreground">
                {fmtDate(article.published_at)}
              </span>
            </div>
            {article.summary ? (
              <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">{article.summary}</p>
            ) : null}
            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <SentimentBadge sentiment={article.sentiment} />
              {article.source ? <span>{article.source}</span> : null}
            </div>
          </a>
        </li>
      ))}
    </ul>
  );
}
