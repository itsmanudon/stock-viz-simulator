/**
 * /stocks/[ticker]/tearsheet — A9.6 (M5.7): a printable one-page company
 * X-ray from routes that already exist (no new data): the latest close and
 * returns, valuation multiples with the P/E band, the forensic scores, the
 * reverse DCF's implied growth, relative strength, the checklist and the
 * latest headlines. Each block drops out when its call fails. Print CSS in
 * globals.css leaves the app chrome off.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PrintButton } from "@/components/print-button";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { ApiError } from "@/lib/api";
import { getRelativeStrength } from "@/lib/api/chart-context";
import { getSymbolChecklist } from "@/lib/api/checklist";
import {
  getForensics,
  getReverseDcf,
  getValuation,
  getValuationHistory,
} from "@/lib/api/fundamentals";
import { getNewsForTicker } from "@/lib/api/news";
import { getSymbol } from "@/lib/api/symbols";
import { checkVisitorLimit } from "@/lib/visitor-limit";

type Params = { ticker: string };

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { ticker } = await params;
  return { title: `${ticker.toUpperCase()} tearsheet` };
}

const fmt = (v: number | null | undefined, d = 2, suffix = "") =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}${suffix}`;

function Block({ title, children, id }: { title: string; children: React.ReactNode; id: string }) {
  return (
    <section className="space-y-2 border-t border-border-muted pt-3" data-testid={id}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default async function TearsheetPage({ params }: { params: Promise<Params> }) {
  const limit = await checkVisitorLimit("stock");
  if (!limit.allowed) return <VisitorLimitNotice retryAfterSeconds={limit.retryAfterSeconds} />;
  const ticker = (await params).ticker.toUpperCase();
  let symbol: Awaited<ReturnType<typeof getSymbol>>;
  try {
    symbol = await getSymbol(ticker);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const [valuation, history, forensics, dcf, rs, checklist, news] = await Promise.all([
    getValuation(ticker).catch(() => null),
    getValuationHistory(ticker, "pe").catch(() => null),
    getForensics(ticker).catch(() => null),
    getReverseDcf(ticker).catch(() => null),
    getRelativeStrength(ticker).catch(() => null),
    getSymbolChecklist(ticker).catch(() => null),
    getNewsForTicker(ticker, 5).catch(() => []),
  ]);
  const metrics = (valuation?.metrics ?? []).filter((m) => m.value !== null).slice(0, 8);
  const bands = history?.bands ?? null;
  return (
    <article className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 sm:px-6" data-tearsheet>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-text-tertiary">Tearsheet · StockViz</p>
          <h1 className="text-2xl font-semibold tracking-[-0.025em]">
            <span className="ticker">{symbol.ticker}</span> {symbol.name}
          </h1>
          <p className="text-xs text-text-secondary">
            {[symbol.sector, symbol.exchange, symbol.currency].filter(Boolean).join(" · ")}
            {symbol.latest
              ? ` · Close ${symbol.latest.close} on ${symbol.latest.ts.slice(0, 10)}`
              : ""}
          </p>
        </div>
        <div className="flex gap-2" data-print-hide>
          <PrintButton />
          <Link href={`/stocks/${encodeURIComponent(ticker)}`} className="text-sm text-brand">
            Back to the stock page
          </Link>
        </div>
      </header>

      {rs && !rs.reason ? (
        <Block title="Returns and Relative Strength" id="tearsheet-rs">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {rs.periods.map((p) => (
              <div key={p.period}>
                <dt className="text-xs text-text-tertiary">
                  {p.period.toUpperCase()} return / RS pct
                </dt>
                <dd className="font-mono text-sm tabular-nums">
                  {fmt(p.return_pct, 1, "%")} / {fmt(p.percentile, 0)}
                </dd>
              </div>
            ))}
            <div>
              <dt className="text-xs text-text-tertiary">From 52-week high</dt>
              <dd className="font-mono text-sm tabular-nums">
                {fmt(rs.distance_from_high_52w_pct, 1, "%")}
              </dd>
            </div>
          </dl>
          <p className="text-xs text-text-tertiary">
            Ranked within {rs.universe.market}; survivorship-biased.
          </p>
        </Block>
      ) : null}

      {metrics.length ? (
        <Block title="Valuation" id="tearsheet-valuation">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {metrics.map((m) => (
              <div key={m.key}>
                <dt className="text-xs text-text-tertiary">{m.label}</dt>
                <dd className="font-mono text-sm tabular-nums">{fmt(m.value, 2)}</dd>
              </div>
            ))}
          </dl>
          {bands && Object.keys(bands).length ? (
            <p className="text-xs text-text-secondary">
              5-year P/E band: p10 {fmt(bands.p10, 1)} · median {fmt(bands.p50, 1)} · p90{" "}
              {fmt(bands.p90, 1)}
              {history?.percentile != null
                ? ` · today at the ${fmt(history.percentile, 0)}th percentile`
                : ""}
            </p>
          ) : null}
          {valuation && !valuation.point_in_time ? (
            <p className="text-xs text-text-tertiary">
              Figures are not point in time ({valuation.basis}).
            </p>
          ) : null}
        </Block>
      ) : null}

      {forensics ? (
        <Block title="Forensic Scores" id="tearsheet-forensics">
          {forensics.financial ? (
            <p className="text-sm text-text-secondary">{forensics.financial_note}</p>
          ) : forensics.reason ? (
            <p className="text-sm text-text-secondary">{forensics.reason}</p>
          ) : (
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <dt className="text-xs text-text-tertiary">Piotroski F</dt>
                <dd className="font-mono text-sm">
                  {forensics.piotroski_score ?? "—"} of {forensics.piotroski_known ?? 9}
                </dd>
              </div>
              {(
                [
                  ["Altman Z''", forensics.altman_z],
                  ["Beneish M", forensics.beneish_m],
                  ["CFO / PAT", forensics.cfo_to_pat],
                ] as const
              ).map(([label, score]) => (
                <div key={label}>
                  <dt className="text-xs text-text-tertiary">{label}</dt>
                  <dd className="font-mono text-sm">
                    {fmt(score?.value, 2)}
                    {score?.zone ? ` (${score.zone})` : ""}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {forensics.fiscal_year_end ? (
            <p className="text-xs text-text-tertiary">
              Fiscal year ending {forensics.fiscal_year_end}.
            </p>
          ) : null}
        </Block>
      ) : null}

      {dcf ? (
        <Block title="Reverse DCF" id="tearsheet-dcf">
          <p className="text-sm">
            {dcf.implied_growth != null
              ? `Today's enterprise value implies ${fmt(dcf.implied_growth * 100, 1, "%")} a year of free cash flow growth for ${dcf.years} years (WACC ${fmt(dcf.wacc * 100, 1, "%")}, terminal ${fmt(dcf.terminal_growth * 100, 1, "%")}).`
              : (dcf.reason ?? "Not computed.")}
          </p>
        </Block>
      ) : null}

      {checklist?.row ? (
        <Block title="Checklist" id="tearsheet-checklist">
          <p className="text-sm">
            {checklist.row.met} of {checklist.row.total} dimensions met ({checklist.row.evaluated}{" "}
            judged) on {checklist.row.session_date}.
          </p>
          <ul className="grid grid-cols-2 gap-1 text-xs sm:grid-cols-3">
            {checklist.row.results.map((r) => (
              <li key={`${r.key}-${r.scope}`}>
                {checklist.dimensions.find((d) => d.key === r.key)?.name ?? r.key}:{" "}
                {r.status === "met" ? "met" : r.status === "not_met" ? "not met" : "unknown"}
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      {news.length ? (
        <Block title="Latest Headlines" id="tearsheet-news">
          <ul className="space-y-1 text-xs">
            {news.map((n) => (
              <li key={n.id}>
                <span className="text-text-tertiary">
                  {(n.published_at ?? n.available_at).slice(0, 10)}
                </span>{" "}
                {n.title}
                {n.source ? <span className="text-text-tertiary"> · {n.source}</span> : null}
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      <footer className="border-t border-border-muted pt-3 text-xs text-text-tertiary">
        Built from stored end-of-day data. Research, not advice. Association, not cause.
      </footer>
    </article>
  );
}
