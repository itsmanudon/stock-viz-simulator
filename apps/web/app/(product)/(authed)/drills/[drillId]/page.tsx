/**
 * /drills/[drillId] — one drill (A4.7, M9.3): A4.6's replay chart and ticket
 * over the drill's own routes (`/v1/drills/{id}/...`). While anonymised the
 * API names the symbol "Stock A" and shifts every date by whole weeks, so
 * nothing on this page (title, URL, chart, orders, fills, news markers) can
 * show the ticker or a real date. The plan form gates the ticket; the reveal
 * shows the symbol, the dates, what happened next and the process score.
 */

import { EyeOff } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { DrillChart } from "@/components/drills/drill-chart";
import { DrillPlanForm } from "@/components/drills/drill-plan-form";
import { DrillRevealButton } from "@/components/drills/drill-reveal";
import { DrillRevealPanel } from "@/components/drills/drill-reveal-panel";
import { PageFrame } from "@/components/page-frame";
import { MetaChip } from "@/components/page-header";
import { ReplayAdvanceControls } from "@/components/replay-controls";
import { ReplayFillTable } from "@/components/replay-fills";
import { ReplayMobileSheet } from "@/components/replay-mobile-sheet";
import { ReplayOrders } from "@/components/replay-orders";
import { ReplayTradeTicket } from "@/components/replay-trade-ticket";
import { getIndicatorCatalog } from "@/lib/api";
import { getDrill, getDrillEvents, getDrillIndicators, listDrillDrawings } from "@/lib/api/drills";
import type { ReplayFill, ReplayOrder } from "@/lib/api/replay";
import { AuthedApiError } from "@/lib/api/server";
import type { Indicators } from "@/lib/api/types";
import type { ChartEvent } from "@/lib/chart-events";
import { DRILL_STATUS_LABEL } from "@/lib/drills";
import { badgesFor } from "@/lib/indicator-badge";
import { formatCurrency, formatSignedCurrency } from "@/lib/portfolio-view-model";
import { formatReplayDate, formatReplayShortDate, replayBarsToChart } from "@/lib/replay";
import { chartLayers, macdSeries, parseStockIndicators, studyFor } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";

// No ticker in the title: a drill is anonymised until revealed.
export const metadata: Metadata = { title: "Drill" };

export default async function DrillPage({
  params,
  searchParams,
}: {
  params: Promise<{ drillId: string }>;
  searchParams: Promise<{ indicators?: string }>;
}) {
  const { drillId: raw } = await params;
  const drillId = Number(raw);
  if (!Number.isInteger(drillId) || drillId <= 0) notFound();
  const requested = await searchParams;

  let drill: Awaited<ReturnType<typeof getDrill>>;
  try {
    drill = await getDrill(drillId);
  } catch (error) {
    if (error instanceof AuthedApiError && error.status === 404) notFound();
    throw error;
  }
  const revealed = drill.status === "revealed";
  const catalog = await getIndicatorCatalog().catch(() => null);
  const selected = parseStockIndicators(
    requested.indicators ?? "",
    catalog ? Object.fromEntries(catalog.map((c) => [c.key, c.parameters])) : null,
  );
  const carried = new URLSearchParams();
  if (selected.length) carried.set("indicators", selected.join(","));
  const [drawings, events, bundleRaw] = await Promise.all([
    listDrillDrawings(drillId).catch(() => null),
    getDrillEvents(drillId).catch(() => null),
    selected.length
      ? getDrillIndicators(drillId, selected).catch(() => null)
      : Promise.resolve(null),
  ]);

  const session = drill.session;
  const currency = session.currency ?? "USD";
  const money = (v: string | number) => formatCurrency(v, currency);
  const label = drill.label;
  const readOnly = session.status !== "active";
  const position = session.positions[0] ?? null;
  const bundle: Indicators = bundleRaw ?? { ticker: label, series: {}, macd: null, meta: {} };
  const rsiKey = selected.find((k) => studyFor(k)?.key === "rsi");
  const macdKey = selected.find((k) => studyFor(k)?.key === "macd");
  const { overlays, panes } = chartLayers(bundle, selected, [rsiKey, macdKey]);
  const chartEvents = (events?.events ?? []) as ChartEvent[];
  const newsItems = (events?.events ?? []).reduce(
    (n, e) => n + (e.type === "news" ? e.count : 0),
    0,
  );
  const summary = drill.summary;
  const triggerShown = drill.trigger_at;
  const atTrigger = session.current_at === triggerShown;

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <header className="flex flex-col gap-3 border-b border-border-muted pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-[-0.025em]" data-testid="drill-label">
            {label}
          </h1>
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-text-tertiary">
            <MetaChip tone={session.status === "active" ? "warning" : "neutral"}>
              {drill.anonymised ? "Shown date" : "Replay date"} ·{" "}
              {formatReplayDate(session.current_at)}
            </MetaChip>
            <span>
              Drill {drill.position + 1} of {drill.deck_name} · {DRILL_STATUS_LABEL[drill.status]} ·
              trigger {formatReplayShortDate(triggerShown)}
              {atTrigger ? " (today in the drill)" : ""}
            </span>
          </div>
        </div>
        <Link
          href="/drills"
          className="text-sm text-text-secondary underline-offset-4 hover:underline"
        >
          All decks
        </Link>
      </header>

      {drill.anonymised ? (
        <p
          className="mt-4 flex items-start gap-2.5 rounded-xl border border-border-muted bg-card px-4 py-3 text-sm text-text-secondary"
          data-testid="drill-anonymised-note"
        >
          <EyeOff className="mt-0.5 size-4 shrink-0 text-text-tertiary" aria-hidden />
          <span>
            Anonymised drill: the symbol, company and headlines are hidden. {drill.date_note}{" "}
            {drill.news_note} The drill opens on the bar where the rule turned true; you see the
            bars before it only. Amounts are in {currency}.
          </span>
        </p>
      ) : null}

      {revealed && drill.reveal ? (
        <DrillRevealPanel
          reveal={drill.reveal}
          score={drill.score ?? null}
          sessionId={session.id}
          currency={currency}
        />
      ) : null}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          {!revealed && !drill.needs_plan ? (
            <ReplayMobileSheet
              sessionId={drill.id}
              ticker={label}
              currentClose={drill.bar.close}
              cash={summary.cash}
              quantityHeld={position?.quantity ?? "0"}
              readOnly={readOnly}
              currency={currency}
              tradable={session.tradable ?? true}
              feeSchedule={session.fee_schedule}
              target="drill"
            />
          ) : null}
          {!revealed && drill.needs_plan ? (
            <div className="border-y border-border-muted py-5 xl:hidden sm:border-x sm:px-5">
              <DrillPlanForm
                drillId={drill.id}
                plan={null}
                currentClose={drill.bar.close}
                cash={summary.cash}
                currency={currency}
                readOnly={readOnly}
              />
            </div>
          ) : null}
          <section
            aria-label={`${label} drill chart`}
            className="border-y border-border-muted bg-surface-elevated sm:border-x"
          >
            <div className="flex flex-wrap items-end justify-between gap-3 px-4 py-3">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.02em] text-text-tertiary">
                  Close
                </p>
                <p className="font-mono text-2xl tabular-nums">{money(drill.bar.close)}</p>
              </div>
              <p className="text-xs text-text-tertiary">
                Visible high {money(summary.visible_high)} · low {money(summary.visible_low)}
                {events ? ` · news: ${newsItems} item${newsItems === 1 ? "" : "s"} so far` : ""}
              </p>
            </div>
            <div className="pb-4">
              {
                <DrillChart
                  drillId={drill.id}
                  ticker={label}
                  search={carried.toString()}
                  indicators={selected}
                  catalog={catalog}
                  initial={drawings}
                  bars={replayBarsToChart(drill.history)}
                  overlays={overlays}
                  rsi={rsiKey ? (bundle.series[rsiKey] ?? null) : null}
                  macd={macdKey ? macdSeries(bundle, macdKey) : null}
                  rsiKey={rsiKey}
                  macdKey={macdKey}
                  panes={panes}
                  badges={badgesFor(selected, catalog)}
                  interval="1d"
                  events={chartEvents}
                  currency={currency}
                />
              }
            </div>
          </section>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5" data-testid="drill-metrics">
            {(
              [
                ["Cash", money(summary.cash)],
                ["Equity", money(summary.equity)],
                ["Total P&L, net", formatSignedCurrency(summary.total_pnl, currency)],
                ["Fees paid", money(summary.fees_paid ?? "0")],
                ["Held", position ? `${Number(position.quantity)} shares` : "None"],
              ] as const
            ).map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-text-tertiary">{k}</dt>
                <dd className="font-mono tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <aside
          className="hidden space-y-6 border-y border-border-muted py-5 xl:block sm:border-x sm:px-5"
          aria-label="Drill plan and ticket"
        >
          {revealed ? (
            <DrillPlanForm
              drillId={drill.id}
              plan={drill.plan ?? null}
              currentClose={drill.bar.close}
              cash={summary.cash}
              currency={currency}
              readOnly
            />
          ) : drill.needs_plan ? (
            <DrillPlanForm
              drillId={drill.id}
              plan={null}
              currentClose={drill.bar.close}
              cash={summary.cash}
              currency={currency}
              readOnly={readOnly}
            />
          ) : (
            <>
              <DrillPlanForm
                drillId={drill.id}
                plan={drill.plan ?? null}
                currentClose={drill.bar.close}
                cash={summary.cash}
                currency={currency}
                readOnly={readOnly}
              />
              <ReplayTradeTicket
                sessionId={drill.id}
                ticker={label}
                currentClose={drill.bar.close}
                cash={summary.cash}
                quantityHeld={position?.quantity ?? "0"}
                readOnly={readOnly}
                currency={currency}
                tradable={session.tradable ?? true}
                feeSchedule={session.fee_schedule}
                target="drill"
              />
            </>
          )}
        </aside>
      </div>

      {!revealed && !drill.needs_plan ? (
        <div className="mt-6 border-y border-border-muted py-5 xl:hidden sm:border-x sm:px-5">
          <DrillPlanForm
            drillId={drill.id}
            plan={drill.plan ?? null}
            currentClose={drill.bar.close}
            cash={summary.cash}
            currency={currency}
            readOnly={readOnly}
          />
        </div>
      ) : null}

      <div className="mt-8 space-y-8">
        <ReplayOrders
          sessionId={drill.id}
          orders={drill.orders as ReplayOrder[]}
          currency={currency}
          readOnly={readOnly || revealed}
          target="drill"
        />
        <ReplayFillTable fills={drill.fills as ReplayFill[]} currency={currency} />
        {!revealed ? (
          <div className="space-y-3">
            <ReplayAdvanceControls
              sessionId={drill.id}
              currentAt={session.current_at}
              hasNext={session.has_next}
              readOnly={readOnly}
              target="drill"
            />
            <div className="flex flex-wrap items-center gap-3">
              <DrillRevealButton drillId={drill.id} finished={readOnly} />
              {readOnly ? (
                <p className="text-sm text-text-secondary">
                  The drill is finished. Reveal it to see the symbol, the dates and your score.
                </p>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </PageFrame>
  );
}
