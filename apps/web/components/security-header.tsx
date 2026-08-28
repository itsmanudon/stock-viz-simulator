import { Bell, BriefcaseBusiness, Star } from "lucide-react";
import Link from "next/link";

import { AlertForm } from "@/components/alert-form";
import { DeltaPill } from "@/components/dashboard/delta-pill";
import { LivePriceBadge } from "@/components/live-price-badge";
import { WatchlistToggle } from "@/components/watchlist-toggle";
import type { SymbolDetail } from "@/lib/api";

function money(value: number | null, currency: string): string {
  if (value === null) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function latestDate(iso: string | undefined): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function SecurityHeader({
  symbol,
  latestClose,
  periodReturnPct,
  timeframe,
  signedIn,
  inWatchlist,
  hasPosition,
  callbackUrl,
}: {
  symbol: SymbolDetail;
  latestClose: number | null;
  periodReturnPct: number | null;
  timeframe: string;
  signedIn: boolean;
  inWatchlist: boolean;
  hasPosition: boolean;
  callbackUrl: string;
}) {
  const positive = periodReturnPct !== null && periodReturnPct >= 0;
  const quoteDate = latestDate(symbol.latest?.ts);

  return (
    <header className="border-b border-border-muted pb-5">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {hasPosition ? (
              <span className="inline-flex items-center gap-1 rounded-sm bg-surface-secondary px-2 py-1 text-3xs font-semibold uppercase tracking-[0.1em] text-text-secondary">
                <BriefcaseBusiness className="size-3" aria-hidden />
                Held
              </span>
            ) : null}
            <span className="text-xs text-text-tertiary">Paper trading available</span>
          </div>
          <h1 className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-2xl font-semibold tracking-[-0.025em] sm:text-3xl">
            <span className="font-mono text-xl tracking-[0.04em] text-brand sm:text-2xl">
              {symbol.ticker}
            </span>
            <span className="min-w-0 truncate">{symbol.name}</span>
          </h1>
          {/* Only list the facts we actually have — an unknown sector and
              exchange previously rendered as "Exchange unavailable · Sector
              unavailable · USD", which is three-quarters apology. */}
          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
            {[symbol.exchange, symbol.sector, symbol.currency]
              .filter((fact): fact is string => Boolean(fact))
              .map((fact, index) => (
                <span key={fact} className="flex items-center gap-x-2">
                  {index > 0 ? <span aria-hidden>·</span> : null}
                  {fact}
                </span>
              ))}
          </p>
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="sm:text-right">
            <p className="text-3xs font-semibold uppercase tracking-[0.14em] text-text-tertiary">
              Latest close{quoteDate ? ` · ${quoteDate}` : ""}
            </p>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 sm:justify-end">
              <span className="font-mono text-3xl font-semibold tracking-[-0.04em] tabular-nums sm:text-4xl">
                {money(latestClose, symbol.currency)}
              </span>
              {periodReturnPct === null ? (
                <span className="font-mono text-sm text-text-tertiary">{timeframe} —</span>
              ) : (
                <DeltaPill
                  value={`${positive ? "+" : ""}${periodReturnPct.toFixed(2)}%`}
                  period={timeframe}
                />
              )}
            </div>
            <div className="mt-1.5 sm:flex sm:justify-end">
              <LivePriceBadge
                ticker={symbol.ticker}
                initialPrice={latestClose}
                currency={symbol.currency}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            {signedIn ? (
              <>
                <WatchlistToggle ticker={symbol.ticker} initialInWatchlist={inWatchlist} compact />
                <AlertForm
                  ticker={symbol.ticker}
                  lastClose={symbol.latest?.close ?? null}
                  currency={symbol.currency}
                />
              </>
            ) : (
              <>
                <Link
                  href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-muted px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
                  aria-label={`Sign in to watch ${symbol.ticker}`}
                >
                  <Star className="size-3.5" aria-hidden />
                  Watch
                </Link>
                <Link
                  href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-muted px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
                  aria-label={`Sign in to set an alert for ${symbol.ticker}`}
                >
                  <Bell className="size-3.5" aria-hidden />
                  Alert
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
