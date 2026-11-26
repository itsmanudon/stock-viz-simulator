/**
 * /replay/[sessionId] — blind historical Replay Lab workspace.
 *
 * Chart, quote, and metrics come only from replay-scoped APIs. No live
 * quotes, SSE, comments, or generic bar history. A4.6: A3's multi-pane chart
 * with the Indicators menu (computed by the API from bars up to the clock),
 * the session's own drawings, its fills and the news whose `available_at`
 * has passed the clock (the replay events route, never the live one); amounts
 * in the session's currency; limit and stop orders that rest across steps.
 */

import { Lock } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FigureStrip } from "@/components/figure-strip";
import { PageFrame } from "@/components/page-frame";
import { MetaChip } from "@/components/page-header";
import { ReplayChart } from "@/components/replay-chart";
import { ReplayAdvanceControls } from "@/components/replay-controls";
import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayForensicsPanel, ReplayScorecard } from "@/components/replay-forensics";
import { ReplayJournalForm } from "@/components/replay-journal";
import { ReplayMobileSheet } from "@/components/replay-mobile-sheet";
import { ReplayOrders } from "@/components/replay-orders";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import { getIndicatorCatalog } from "@/lib/api";
import {
  getReplayEvents,
  getReplayFills,
  getReplayForensics,
  getReplayHistory,
  getReplayIndicators,
  getReplayJournal,
  getReplayMarket,
  getReplayOrders,
  getReplaySession,
  getReplaySummary,
  listReplayDrawings,
} from "@/lib/api/replay";
import { AuthedApiError } from "@/lib/api/server";
import type { Indicators } from "@/lib/api/types";
import type { ChartEvent } from "@/lib/chart-events";
import { badgesFor } from "@/lib/indicator-badge";
import { formatCurrency, formatQuantity, formatSignedCurrency } from "@/lib/portfolio-view-model";
import {
  datesDiffer,
  formatReplayClock,
  formatReplayDate,
  isIntradayInterval,
  replayBarsToChart,
  replayIntervalLabel,
  replayProfileLabel,
  replayStatusLabel,
} from "@/lib/replay";
import {
  chartLayers,
  macdSeries,
  parseStockIndicators,
  parseStockInterval,
  studyFor,
} from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Replay session" };

export default async function ReplaySessionPage({
  params,
  searchParams,
}: {
  params: Promise<{ sessionId: string }>;
  searchParams: Promise<{
    requestedStart?: string;
    requestedEnd?: string;
    view?: string;
    indicators?: string;
  }>;
}) {
  const { sessionId: rawId } = await params;
  const sessionId = Number(rawId);
  if (!Number.isInteger(sessionId) || sessionId <= 0) notFound();

  const requested = await searchParams;
  const view = requested.view === "forensics" ? "forensics" : "replay";

  // A4.6: the replay chart starts with no studies; the menu adds them (URL state).
  const catalog = view === "replay" ? await getIndicatorCatalog().catch(() => null) : null;
  const selectedIndicators = parseStockIndicators(
    requested.indicators ?? "",
    catalog ? Object.fromEntries(catalog.map((c) => [c.key, c.parameters])) : null,
  );
  const carried = new URLSearchParams();
  for (const key of ["requestedStart", "requestedEnd"] as const) {
    const value = requested[key];
    if (value) carried.set(key, value);
  }
  if (selectedIndicators.length) carried.set("indicators", selectedIndicators.join(","));

  try {
    const [session, market, history, summary, fills, forensics, journal] = await Promise.all([
      getReplaySession(sessionId),
      getReplayMarket(sessionId),
      getReplayHistory(sessionId),
      getReplaySummary(sessionId),
      getReplayFills(sessionId),
      getReplayForensics(sessionId),
      getReplayJournal(sessionId),
    ]);
    // Everything on the chart is replay-scoped and cut at the clock by the API.
    const [orders, drawings, replayEvents, indicatorBundle] =
      view === "replay"
        ? await Promise.all([
            getReplayOrders(sessionId).catch(() => []),
            listReplayDrawings(sessionId).catch(() => null),
            getReplayEvents(sessionId).catch(() => null),
            selectedIndicators.length
              ? getReplayIndicators(sessionId, selectedIndicators).catch(() => null)
              : Promise.resolve(null),
          ])
        : [[], null, null, null];
    const currency = session.currency ?? "USD";
    const money = (value: string | number) => formatCurrency(value, currency);
    const bundle: Indicators = indicatorBundle ?? {
      ticker: session.ticker,
      series: {},
      macd: null,
      meta: {},
    };
    const rsiKey = selectedIndicators.find((k) => studyFor(k)?.key === "rsi");
    const macdKey = selectedIndicators.find((k) => studyFor(k)?.key === "macd");
    const { overlays, panes } = chartLayers(bundle, selectedIndicators, [rsiKey, macdKey]);
    const chartEvents = (replayEvents?.events ?? []) as ChartEvent[];
    const newsCount = chartEvents.filter((e) => e.type === "news").length;

    const readOnly = session.status !== "active";
    const position = session.positions[0] ?? null;
    const chartBars = replayBarsToChart(history);
    const chartHigh = Math.max(...history.map((bar) => Number(bar.high)), Number(market.bar.high));
    const interval = session.interval ?? "1d";
    const intraday = isIntradayInterval(interval);
    const profileLabel = replayProfileLabel(session.profile_name, session.model_version);
    const intrabar = session.profile_name === "intrabar_ohlc";
    const barsWord = intraday ? `${interval} bars built from stored minutes` : "daily bars";
    const startChanged = datesDiffer(requested.requestedStart, session.start_at);
    const endChanged = datesDiffer(requested.requestedEnd, session.end_at);

    return (
      <PageFrame width="workstation" className="py-6 sm:py-8">
        <header className="flex flex-col gap-3 border-b border-border-muted pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-2xs font-medium tracking-[0.02em] text-text-secondary">
              {session.status === "completed" ? "Replay Review" : "Replay"} · Historical Session ·{" "}
              {intraday ? `${replayIntervalLabel(interval)} Bars` : "Daily Data"}
            </p>
            <h1 className="mt-1.5 text-3xl font-semibold tracking-[-0.025em]">{session.ticker}</h1>
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-text-tertiary">
              <MetaChip tone={session.status === "active" ? "warning" : "neutral"}>
                Replay {intraday ? "time" : "date"} ·{" "}
                {formatReplayClock(session.current_at, interval)}
              </MetaChip>
              <MetaChip tone="neutral">
                <span data-testid="replay-profile">Fill model · {profileLabel}</span>
              </MetaChip>
              <span>
                {replayStatusLabel(session.status)} · stored {barsWord}{" "}
                {session.start_at.slice(0, 10)} → {session.end_at.slice(0, 10)} ·{" "}
                <span data-testid="replay-bar-count">Bar {history.length}</span>
              </span>
            </div>
          </div>
          <Link
            href="/replay"
            className="text-sm text-text-secondary underline-offset-4 hover:underline"
          >
            All replays
          </Link>
        </header>

        {/* The blind rule leads the page (Aurora board v3): it shapes every
            figure below, so it is stated before any of them. */}
        <p className="mt-4 flex items-start gap-2.5 rounded-xl border border-border-muted bg-card px-4 py-3 text-sm text-text-secondary">
          <Lock className="mt-0.5 size-4 shrink-0 text-text-tertiary" aria-hidden />
          <span>
            Blind session: you see bars, indicators and news up to the replay{" "}
            {intraday ? "time" : "date"} only. Market orders fill at the current bar&apos;s stored
            close; resting orders are{" "}
            {intrabar
              ? "judged on each later bar's range, the open first"
              : "checked against each later close"}
            , with no spread and no slippage
            {session.fee_schedule && session.fee_schedule !== "none"
              ? ", and pay the exchange's charges in force on that date"
              : ""}
            . Amounts are in {currency}.
          </span>
        </p>

        {startChanged || endChanged ? (
          <p className="mt-4 border-y border-border-muted py-3 text-sm text-text-secondary sm:border-x sm:px-4">
            Requested {requested.requestedStart} → {requested.requestedEnd}. Resolved{" "}
            {session.start_at.slice(0, 10)} → {session.end_at.slice(0, 10)} to stored {barsWord}.
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
                You completed this replay without placing a trade.{" "}
                <Link
                  href={`/replay/${session.id}?view=forensics`}
                  className="underline-offset-4 hover:underline"
                >
                  Review decisions
                </Link>{" "}
                still compares replay equity with same-symbol buy-and-hold.
              </p>
            ) : (
              <p className="mt-2 text-sm text-text-secondary">
                This historical range is finished.{" "}
                <Link
                  href={`/replay/${session.id}?view=forensics`}
                  className="underline-offset-4 hover:underline"
                >
                  Review decisions
                </Link>{" "}
                — replay versus buy-and-hold, MAE/MFE, episodes, and journal.
              </p>
            )}
            <FigureStrip
              label="Replay summary"
              className="mt-4"
              figures={[
                { label: "Starting equity", value: money(summary.starting_cash) },
                { label: "Final equity", value: money(summary.equity) },
                {
                  label: "Total return",
                  value: (
                    <Signed raw={summary.return_pct}>
                      {Number(summary.return_pct).toFixed(2)}%
                    </Signed>
                  ),
                },
                { label: "Fills", value: String(summary.fills_count) },
                {
                  label: "Realized P&L",
                  value: (
                    <Signed raw={summary.realized_pnl}>
                      {formatSignedCurrency(summary.realized_pnl, currency)}
                    </Signed>
                  ),
                },
                {
                  label: "Unrealized P&L",
                  value: (
                    <Signed raw={summary.unrealized_pnl}>
                      {formatSignedCurrency(summary.unrealized_pnl, currency)}
                    </Signed>
                  ),
                },
              ]}
            />
            {view === "replay" ? (
              <div className="mt-5">
                <ReplayScorecard forensics={forensics} />
              </div>
            ) : null}
          </section>
        ) : null}

        {session.status === "cancelled" ? (
          <p className="mt-4 border-y border-border-muted py-3 text-sm text-text-secondary sm:border-x sm:px-4">
            This replay was cancelled and is now read-only. Analysis is available through the
            cancellation point.{" "}
            <Link
              href={`/replay/${session.id}?view=forensics`}
              className="underline-offset-4 hover:underline"
            >
              Review decisions
            </Link>
          </p>
        ) : null}

        <nav aria-label="Replay workspace" className="mt-6 border-b border-border-muted">
          <ul className="flex gap-1">
            <li>
              <Link
                href={`/replay/${session.id}`}
                aria-current={view === "replay" ? "page" : undefined}
                className={cn(
                  "inline-flex h-10 items-center border-b-2 px-3 text-sm",
                  view === "replay"
                    ? "border-brand font-medium text-foreground"
                    : "border-transparent text-text-tertiary hover:text-foreground",
                )}
              >
                Replay
              </Link>
            </li>
            <li>
              <Link
                href={`/replay/${session.id}?view=forensics`}
                aria-current={view === "forensics" ? "page" : undefined}
                className={cn(
                  "inline-flex h-10 items-center border-b-2 px-3 text-sm",
                  view === "forensics"
                    ? "border-brand font-medium text-foreground"
                    : "border-transparent text-text-tertiary hover:text-foreground",
                )}
              >
                Forensics
              </Link>
            </li>
          </ul>
        </nav>

        {view === "forensics" ? (
          <div className="mt-6 space-y-8">
            <ReplayForensicsPanel forensics={forensics} />
            <ReplayJournalForm
              sessionId={session.id}
              journal={journal}
              hasFills={fills.length > 0}
              completed={session.status === "completed"}
            />
          </div>
        ) : (
          <>
            <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="min-w-0 space-y-4">
                <ReplayMobileSheet
                  sessionId={session.id}
                  ticker={session.ticker}
                  currentClose={market.bar.close}
                  cash={summary.cash}
                  quantityHeld={position?.quantity ?? "0"}
                  readOnly={readOnly}
                  currency={currency}
                  tradable={session.tradable ?? true}
                  feeSchedule={session.fee_schedule}
                  profileName={session.profile_name}
                  profileVersion={session.model_version}
                />
                <section
                  aria-label={`${session.ticker} replay price chart`}
                  className="border-y border-border-muted bg-surface-elevated sm:border-x"
                >
                  <div className="flex flex-wrap items-end justify-between gap-3 px-4 py-3">
                    <div>
                      <p className="text-[11px] font-semibold tracking-[0.02em] text-text-tertiary">
                        Replay Close
                      </p>
                      <p className="font-mono text-2xl tabular-nums">{money(market.bar.close)}</p>
                    </div>
                    <p className="text-xs text-text-tertiary">
                      Visible high {money(summary.visible_high)} · low {money(summary.visible_low)}
                      {replayEvents
                        ? ` · ${newsCount} news day${newsCount === 1 ? "" : "s"} so far`
                        : ""}
                    </p>
                  </div>
                  <div className="pb-4">
                    <ReplayChart
                      sessionId={session.id}
                      ticker={session.ticker}
                      search={carried.toString()}
                      indicators={selectedIndicators}
                      catalog={catalog}
                      initial={drawings}
                      bars={chartBars}
                      overlays={overlays}
                      rsi={rsiKey ? (bundle.series[rsiKey] ?? null) : null}
                      macd={macdKey ? macdSeries(bundle, macdKey) : null}
                      rsiKey={rsiKey}
                      macdKey={macdKey}
                      panes={panes}
                      badges={badgesFor(selectedIndicators, catalog)}
                      interval={parseStockInterval(interval)}
                      events={chartEvents}
                      currency={currency}
                    />
                    {selectedIndicators.length && indicatorBundle === null ? (
                      <p className="px-3 pt-2 text-xs text-text-tertiary">
                        The indicators could not be loaded; the chart shows the bars only.
                      </p>
                    ) : null}
                  </div>
                </section>
                <p className="sr-only">
                  Chart dataset high {chartHigh}. Future prices are not included.{" "}
                  {fills.length === 0
                    ? "No trade markers."
                    : `Trade markers: ${fills.map((fill) => `${titleCase(fill.side)} on ${formatReplayDate(fill.evaluated_at)}`).join("; ")}.`}
                </p>
                <ReplayMetrics summary={summary} currency={currency} />
                {session.status === "active" && fills.length === 0 ? (
                  <p className="text-sm text-text-secondary">
                    <Link
                      href={`/replay/${session.id}?view=forensics`}
                      className="underline-offset-4 hover:underline"
                    >
                      Record your thesis
                    </Link>{" "}
                    before the first fill. Thesis fields lock once a trade exists.
                  </p>
                ) : null}
                <ReplayAssumptions
                  profileLabel={profileLabel}
                  assumptions={session.profile_assumptions ?? []}
                  intrabar={intrabar}
                  barsWord={barsWord}
                />
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
                  currency={currency}
                  tradable={session.tradable ?? true}
                  feeSchedule={session.fee_schedule}
                  profileName={session.profile_name}
                  profileVersion={session.model_version}
                />
              </aside>
            </div>

            <div className="mt-8 space-y-8">
              <ReplayPositionCard
                ticker={session.ticker}
                position={position}
                close={market.bar.close}
                unrealized={summary.unrealized_pnl}
                currency={currency}
              />
              <ReplayOrders
                sessionId={session.id}
                orders={orders}
                currency={currency}
                readOnly={readOnly}
                profileName={session.profile_name}
              />
              <ReplayFillTable fills={fills} currency={currency} />
              <ReplayAdvanceControls
                sessionId={session.id}
                currentAt={session.current_at}
                hasNext={session.has_next}
                readOnly={readOnly}
                interval={interval}
              />
            </div>
          </>
        )}
      </PageFrame>
    );
  } catch (error) {
    if (error instanceof AuthedApiError && error.status === 404) notFound();
    throw error;
  }
}

/** A signed figure: the sign's colour, plus an arrow so it never relies on colour. */
function Signed({ raw, children }: { raw: string; children: React.ReactNode }) {
  const value = Number(raw);
  return (
    <span className={signedClass(raw)}>
      {value > 0 ? <span aria-hidden>▲ </span> : value < 0 ? <span aria-hidden>▼ </span> : null}
      {children}
    </span>
  );
}

function signedClass(raw: string): string {
  const value = Number(raw);
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "";
}

function ReplayMetrics({
  summary,
  currency,
}: {
  summary: {
    cash: string;
    equity: string;
    total_pnl: string;
    return_pct: string;
    current_close: string;
    fees_paid?: string;
  };
  currency: string;
}) {
  const items = [
    ["Replay close", formatCurrency(summary.current_close, currency)],
    ["Cash", formatCurrency(summary.cash, currency)],
    ["Equity", formatCurrency(summary.equity, currency)],
    ["Total P&L, net", formatSignedCurrency(summary.total_pnl, currency)],
    ["Fees paid", formatCurrency(summary.fees_paid ?? "0", currency)],
    ["Return", `${Number(summary.return_pct).toFixed(2)}%`],
  ] as const;
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
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
  currency,
}: {
  ticker: string;
  close: string;
  unrealized: string;
  currency: string;
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
          <dd className="font-mono tabular-nums">{formatCurrency(position.avg_cost, currency)}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Market value</dt>
          <dd className="font-mono tabular-nums">{formatCurrency(marketValue, currency)}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-tertiary">Unrealized P&amp;L</dt>
          <dd className={cn("font-mono tabular-nums", signedClass(unrealized))}>
            {formatSignedCurrency(unrealized, currency)}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function ReplayAssumptions({
  profileLabel,
  assumptions,
  intrabar,
  barsWord,
}: {
  profileLabel: string;
  assumptions: string[];
  intrabar: boolean;
  barsWord: string;
}) {
  return (
    <details className="mt-6 text-xs leading-5 text-text-tertiary">
      <summary className="cursor-pointer font-medium text-text-secondary">
        Simulation assumptions
      </summary>
      <ul className="mt-2 space-y-1" data-testid="replay-assumptions">
        <li>Execution model: {profileLabel}</li>
        {assumptions.map((line) => (
          <li key={line}>{line}</li>
        ))}
        <li>
          {intrabar
            ? "Limit, stop and target orders: judged on each later bar's open, high and low as you step; nothing reserved"
            : "Limit and stop orders: checked against each later close as you step, filled at that close; nothing reserved"}
        </li>
        <li>Brackets: the stop and the target rest once the entry fills; one cancels the other</li>
        <li>Indicators: computed from bars up to the replay clock (warm-up from earlier bars)</li>
        <li>News: shown once its publication time is at or before the replay clock</li>
        <li>Drawings: this session&apos;s own; live-chart drawings are not shown</li>
        <li>Data: stored {barsWord}</li>
        <li>Spread: not modelled</li>
        <li>Slippage: not modelled</li>
      </ul>
    </details>
  );
}
