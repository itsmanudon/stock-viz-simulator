"use client";

/**
 * Route-level error boundary.
 *
 * The API runs on Render's free tier, which spins down after ~15 minutes idle
 * and takes 30-60s to cold start. `lib/api/client.ts` retries with backoff, but
 * a long enough cold start still throws — and without this every route showed
 * Next's raw error page. `reset()` re-renders the segment, which is usually all
 * a woken-up origin needs.
 */

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-lg flex-col items-start gap-4 px-4 py-24">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground">
        We couldn&apos;t load this page. The market data service may still be starting up — that can
        take up to a minute after a period of inactivity.
      </p>
      <div className="flex gap-3">
        <Button type="button" onClick={reset}>
          Try again
        </Button>
        <Button type="button" variant="ghost" onClick={() => window.location.reload()}>
          Reload the page
        </Button>
      </div>
      {error.digest ? (
        <p className="font-mono text-xs text-muted-foreground">Reference: {error.digest}</p>
      ) : null}
    </div>
  );
}
