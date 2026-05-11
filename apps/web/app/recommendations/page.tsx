/**
 * /recommendations — cards keyed by ticker showing the latest score.
 *
 * Pulls from /v1/recommendations (pre-computed by the daily scheduler job).
 * The page is the operator-friendly view; the algo itself lives in
 * apps/api/services/recommend/.
 */

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { getRecommendations } from "@/lib/api";

const VOTE_THRESHOLD = 4;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<{ min?: string }>;
}) {
  const { min: rawMin } = await searchParams;
  const minScore = Math.max(0, Math.min(6, Number.parseInt(rawMin ?? "0", 10) || 0));

  const recs = await getRecommendations({ minScore, limit: 100 });

  const lastComputed = recs.length
    ? recs.reduce(
        (latest, r) => (r.computed_at > latest ? r.computed_at : latest),
        recs[0].computed_at,
      )
    : null;

  return (
    <div className="container mx-auto px-6 py-10">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Recommendations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Algorithmic scores from a 6-vote technical signal. Not financial advice.
          </p>
          {lastComputed ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Last computed {fmtDate(lastComputed)}
            </p>
          ) : null}
        </div>
        <nav className="flex gap-1 text-xs">
          {[0, 3, 4, 5].map((threshold) => (
            <Link
              key={threshold}
              href={threshold === 0 ? "/recommendations" : `/recommendations?min=${threshold}`}
              className={`rounded-md border px-3 py-1.5 transition hover:bg-accent ${
                minScore === threshold ? "border-primary text-foreground" : "text-muted-foreground"
              }`}
            >
              {threshold === 0 ? "All" : `≥ ${threshold}`}
            </Link>
          ))}
        </nav>
      </header>

      {recs.length === 0 ? (
        <p className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          No recommendations match this filter. Run{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">stockviz recommend</code> to
          recompute, or relax the score threshold.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {recs.map((rec) => {
            const buy = rec.score >= VOTE_THRESHOLD;
            return (
              <Link key={rec.ticker} href={`/stocks/${rec.ticker}`} className="block">
                <Card className="h-full transition hover:border-primary/50">
                  <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
                    <div>
                      <div className="font-mono text-lg font-semibold">{rec.ticker}</div>
                      <div className="text-xs text-muted-foreground">{rec.name}</div>
                      {rec.sector ? (
                        <div className="mt-1 text-xs text-muted-foreground">{rec.sector}</div>
                      ) : null}
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <Badge variant={buy ? "default" : "secondary"}>{buy ? "BUY" : "HOLD"}</Badge>
                      <span className="font-mono text-xs text-muted-foreground">{rec.score}/6</span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {rec.rationale.length > 0 ? (
                      <ul className="space-y-1 text-xs text-muted-foreground">
                        {rec.rationale.map((reason) => (
                          <li key={reason} className="flex gap-2">
                            <span aria-hidden>·</span>
                            <span>{reason}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-muted-foreground">No signals — the score is 0.</p>
                    )}
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
