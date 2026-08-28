/**
 * /replay/[sessionId] — blind historical Replay Lab workspace.
 *
 * Chart, quote, and metrics come only from replay-scoped APIs. No live
 * quotes, SSE, news, comments, or generic bar history.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { PageFrame } from "@/components/page-frame";
import { PriceChart } from "@/components/price-chart";
import { ReplayAdvanceControls } from "@/components/replay-controls";
import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayMobileSheet } from "@/components/replay-mobile-sheet";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import {
  getReplayFills,
  getReplayHistory,
  getReplayMarket,
  getReplaySession,
  getReplaySummary,
} from "@/lib/api/replay";
import { AuthedApiError } from "@/lib/api/server";
import { formatCurrency, formatQuantity, formatSignedCurrency } from "@/lib/portfolio-view-model";
import {
  REPLAY_PROFILE_LABEL,
  datesDiffer,
  formatReplayDate,
  replayBarsToChart,
  replayStatusLabel,
} from "@/lib/replay";
import { cn } from "@/lib/utils";

export default async function ReplaySessionPage({
  params,
  searchParams,
}: {
  params: Promise<{ sessionId: string }>;
  searchParams: Promise<{ requestedStart?: string; requestedEnd?: string }>;
}) {
  const { sessionId: rawId } = await params;
  const sessionId = Number(rawId);
  if (!Number.isInteger(sessionId) || sessionId <= 0) notFound();

  const requested = await searchParams;

  try {
    const [session, market, history, summary, fills] = await Promise.all([
      getReplaySession(sessionId),
      getReplayMarket(sessionId),
      getReplayHistory(sessionId),
      getReplaySummary(sessionId),
      getReplayFills(sessionId),
    ]);

    const readOnly = session.status !== "active";
    const position = session.positions[0] ?? null;
    const chartBars = replayBarsToChart(history);
    const chartHigh = Math.max(...history.map((bar) => Number(bar.high)), Number(market.bar.high));
    const startChanged = datesDiffer(requested.requestedStart, session.start_at);
    const endChanged = datesDiffer(requested.requestedEnd, session.end_at);

    return (
      <PageFrame width="workstation" className="py-6 sm:py-8">
        <header className="flex flex-col gap-3 border-b border-border-muted pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.14em] text-brand uppercase">
              Replay · Historical session · Daily data
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">{session.ticker}</h1>
            <p className="mt-1 text-lg text-text-secondary">
              {formatReplayDate(session.current_at)}
            </p>
            <p className="mt-1 text-xs text-text-tertiary">
              {replayStatusLabel(session.status)} · stored sessions {session.start_at.slice(0, 10)}{" "}
              → {session.end_at.slice(0, 10)}
            </p>
          </div>
          <Link
            href="/replay"
            className="text-sm text-text-secondary underline-offset-4 hover:underline"
          >
            All replays
          </Link>
        </header>

        {startChanged || endChanged ? (
          <p className="mt-4 border-y border-border-muted py-3 text-sm text-text-secondary sm:border-x sm:px-4">
            Requested {requested.requestedStart} → {requested.requestedEnd}. Resolved{" "}
            {session.start_at.slice(0, 10)} → {session.end_at.slice(0, 10)} to stored market
            sessions.
          </p>
        ) : null}

        {session.status === "completed" ? (
          <section
            aria-labelledby="replay-complete-heading"
            className="mt-6 border-y border-border-muted py-5 sm:border-x sm:px-6"
          >
            <h2 id="replay-complete-heading" className="text-base font-semibold">
              Replay complete
            </h2>
            {fills.length === 0 ? (
              <p className="mt-2 text-sm text-text-secondary">
                You completed this replay without placing a trade.
              </p>
            ) : (
              <p className="mt-2 text-sm text-text-secondary">
                This historical range is finished. Review the isolated book below or start another
                replay.
              </p>
            )}
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-xs text-text-tertiary">Starting equity</dt>
                <dd className="font-mono tabular-nums">{formatCurrency(summary.starting_cash)}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-tertiary">Final equity</dt>
                <dd className="font-mono tabular-nums">{formatCurrency(summary.equity)}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-tertiary">Total return</dt>
                <dd className={cn("font-mono tabular-nums", signedClass(summary.return_pct))}>
                  {Number(summary.return_pct).toFixed(2)}%
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-tertiary">Fills</dt>
                <dd className="font-mono tabular-nums">{summary.fills_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-tertiary">Realized P&amp;L</dt>
                <dd className={cn("font-mono tabular-nums", signedClass(summary.realized_pnl))}>
                  {formatSignedCurrency(summary.realized_pnl)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-tertiary">Unrealized P&amp;L</dt>
                <dd className={cn("font-mono tabular-nums", signedClass(summary.unrealized_pnl))}>
                  {formatSignedCurrency(summary.unrealized_pnl)}
                </dd>
              </div>
            </dl>
          </section>
        ) : null}

        {session.status === "cancelled" ? (
          <p className="mt-4 border-y border-border-muted py-3 text-sm text-text-secondary sm:border-x sm:px-4">
            This replay was cancelled and is now read-only.
          </p>
        ) : null}

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-4">
            <ReplayMobileSheet
              sessionId={session.id}
              ticker={session.ticker}
              currentClose={market.bar.close}
              cash={summary.cash}
              quantityHeld={position?.quantity ?? "0"}
              readOnly={readOnly}
            />
            <section
              aria-label={`${session.ticker} replay price chart`}
              className="border-y border-border-muted bg-surface-elevated sm:border-x"
            >
              <div className="flex flex-wrap items-end justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-text-tertiary uppercase">
                    Replay close
                  </p>
                  <p className="font-mono text-2xl tabular-nums">
                    {formatCurrency(market.bar.close)}
                  </p>
                </div>
                <p className="text-xs text-text-tertiary">
                  Visible high {formatCurrency(summary.visible_high)} · low{" "}
                  {formatCurrency(summary.visible_low)}
                </p>
              </div>
              <div className="px-2 pb-4">
                <PriceChart bars={chartBars} />
              </div>
            </section>
            <p className="sr-only">
              Chart dataset high {chartHigh}. Future prices are not included.
            </p>
            <ReplayMetrics summary={summary} />
            <ReplayAssumptions />
          </div>
          <aside
            className="hidden border-y border-border-muted py-5 xl:block sm:border-x sm:px-5"
            aria-label={`Replay ticket ${session.ticker}`}
          >
            <ReplayTradeTicket
              sessionId={session.id}
              ticker={session.ticker}
              currentClose={market.bar.close}
              cash={summary.cash}
              quantityHeld={position?.quantity ?? "0"}
              readOnly={readOnly}
            />
          </aside>
        </div>

        <div className="mt-8 space-y-8">
          <ReplayPositionCard
            ticker={session.ticker}
            position={position}
            close={market.bar.close}
            unrealized={summary.unrealized_pnl}
          />
          <ReplayFillTable fills={fills} />
          <ReplayAdvanceControls
            sessionId={session.id}
            currentAt={session.current_at}
            hasNext={session.has_next}
            readOnly={readOnly}
          />
        </div>
      </PageFrame>
    );
  } catch (error) {
    if (error instanceof AuthedApiError && error.status === 404) notFound();
    throw error;
  }
}

function signedClass(raw: string): string {
  const value = Number(raw);
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "";
}

function ReplayMetrics({
  summary,
}: {
  summary: {
    cash: string;
    equity: string;
    total_pnl: string;
    return_pct: string;
    current_close: string;
  };
}) {
  const items = [
    ["Replay close", formatCurrency(summary.current_close)],
    ["Cash", formatCurrency(summary.cash)],
    ["Equity", formatCurrency(summary.equity)],
    ["Total P&L", formatSignedCurrency(summary.total_pnl)],
    ["Return", `${Number(summary.return_pct).toFixed(2)}%`],
  ] as const;
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-text-tertiary">{label}</dt>
          <dd className="font-mono tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ReplayPositionCard({
  ticker,
  close,
  unrealized,
  position,
}: {
  ticker: string;
  close: string;
  unrealized: string;
  position: { ticker: string; quantity: string; avg_cost: string } | null;
}) {
  if (!position || Number(position.quantity) === 0) {
    return (
      <ResearchEmptyState title="No open replay position.">
        A market buy at this session&apos;s close opens a holding on the isolated replay book.
      </ResearchEmptyState>
    );
  }
  const marketValue = Number(position.quantity) * Number(close);
  return (
    <section aria-labelledby="replay-position-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-position-heading"
        title="Replay position"
        description="Marked at the current replay close, not a live quote."
      />
      <dl className="grid grid-cols-2 gap-3 border-y border-border-muted py-4 text-sm sm:grid-cols-5 sm:border-x sm:px-6">
        <div>
          <dt className="text-xs text-text-tertiary">Symbol</dt>
          <dd>{ticker}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Quantity</dt>
          <dd className="font-mono tabular-nums">{formatQuantity(position.quantity)}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Average cost</dt>
          <dd className="font-mono tabular-nums">{formatCurrency(position.avg_cost)}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Market value</dt>
          <dd className="font-mono tabular-nums">{formatCurrency(marketValue)}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Unrealized P&amp;L</dt>
          <dd className={cn("font-mono tabular-nums", signedClass(unrealized))}>
            {formatSignedCurrency(unrealized)}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function ReplayAssumptions() {
  return (
    <details className="mt-6 text-xs leading-5 text-text-tertiary">
      <summary className="cursor-pointer font-medium text-text-secondary">
        Simulation assumptions
      </summary>
      <ul className="mt-2 space-y-1">
        <li>Execution model: {REPLAY_PROFILE_LABEL}</li>
        <li>Data: stored 1d bars</li>
        <li>Fill model: current observable close</li>
        <li>Spread: not modelled</li>
        <li>Slippage: not modelled</li>
      </ul>
    </details>
  );
}
