/**
 * The hero's product panel — the page's signature object.
 *
 * A cropped, non-interactive replica of the stock workspace rendered on the
 * `.panel-inset` dark ground, so it reads the same way on paper and in dark
 * mode. Everything numeric in here is REAL: the price, change, sparkline, and
 * the OHLC/volume row all come from stored daily bars. Nothing is invented —
 * there is no fake portfolio or fabricated P&L, because the marketing copy
 * promises simulated fills on end-of-day data and the visual has to match.
 *
 * The whole panel is `aria-hidden`: it is a picture of the product with fake
 * chrome (a rail of icons, inert range chips), and the same prices are
 * available as real links in the ticker strip directly below it. Announcing
 * both would just duplicate them.
 */

import { BriefcaseBusiness, ChartCandlestick, ListFilter, Signal } from "lucide-react";

import { Sparkline } from "@/components/sparkline";
import { ApiError, getBars, listSymbols } from "@/lib/api";
import type { Bar } from "@/lib/api/types";

// Tried in order; the first with enough stored history wins. A cold database
// that has only backfilled part of the universe still gets a chart. Liquid
// names with the deepest, freshest daily history lead so the hero never shows
// a months-stale price.
const CANDIDATES = ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "NVDA", "AAPL", "MSFT"];

const RAIL_ICONS = [ChartCandlestick, ListFilter, Signal, BriefcaseBusiness];
const RANGES = ["1M", "3M", "6M", "1Y"];

type PanelData = {
  ticker: string;
  name: string;
  currency: string;
  bars: Bar[];
};

async function loadPanel(): Promise<PanelData | null> {
  const meta = new Map<string, { name: string; currency: string }>();
  try {
    const symbols = await listSymbols();
    for (const s of symbols) meta.set(s.ticker, { name: s.name, currency: s.currency });
  } catch {
    // Names/currency are cosmetic here — fall back to the ticker / USD.
  }

  for (const ticker of CANDIDATES) {
    try {
      const bars = await getBars(ticker, { limit: 60 });
      if (bars.length >= 2) {
        const m = meta.get(ticker);
        return { ticker, name: m?.name ?? ticker, currency: m?.currency ?? "USD", bars };
      }
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      // Try the next candidate.
    }
  }
  return null;
}

function fmtMoney(n: number, currency: string): string {
  const digits = currency === "JPY" ? 0 : 2;
  try {
    return n.toLocaleString("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  } catch {
    return `${currency} ${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

function fmtVolume(n: number): string {
  return n.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
}

/** Chrome that renders identically whether or not the API returned data. */
function PanelFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="panel-inset panel-glow shadow-2xl shadow-black/10" aria-hidden>
      <div className="flex">
        <div className="hidden w-12 shrink-0 flex-col items-center gap-5 border-r border-border-muted py-4 sm:flex">
          <span className="size-5 rounded-md border border-brand/40 bg-brand/10" />
          {RAIL_ICONS.map((Icon, index) => (
            <Icon
              key={Icon.displayName ?? index}
              className={`size-4 ${index === 0 ? "text-brand" : "text-text-tertiary"}`}
            />
          ))}
        </div>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

export async function HeroPanel() {
  const data = await loadPanel();

  // No stored bars anywhere: keep the frame so the hero's two-column layout
  // doesn't collapse, but don't draw an empty chart pretending to be one.
  if (!data) {
    return (
      <PanelFrame>
        <div className="flex h-72 items-center justify-center px-6 text-center">
          <p className="font-mono text-2xs text-text-tertiary">
            Awaiting the first end-of-day ingest
          </p>
        </div>
      </PanelFrame>
    );
  }

  const closes = data.bars.map((b) => Number(b.close));
  const latest = data.bars[data.bars.length - 1];
  const close = closes[closes.length - 1];
  const prev = closes[closes.length - 2];
  const changePct = prev !== 0 ? ((close - prev) / prev) * 100 : 0;
  const up = changePct >= 0;

  return (
    <PanelFrame>
      <div className="flex items-start justify-between gap-4 border-b border-border-muted px-4 py-3.5">
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold tracking-wide">{data.ticker}</p>
          <p className="truncate text-2xs text-text-tertiary">{data.name}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-lg leading-none font-semibold tabular-nums">
            {fmtMoney(close, data.currency)}
          </p>
          <p
            className={`mt-1 font-mono text-2xs tabular-nums ${up ? "text-positive" : "text-negative"}`}
          >
            {up ? "+" : ""}
            {changePct.toFixed(2)}%
          </p>
        </div>
      </div>

      <div className="px-4 pt-4">
        <Sparkline
          closes={closes}
          // `baseline` is the start of the window, so the fill shows the move
          // over the whole period rather than just the last session.
          showBaseline
          periodLabel={`${closes.length}-session`}
          className="h-40 w-full sm:h-48"
        />
      </div>

      <div className="flex items-center gap-1.5 px-4 pt-3 pb-3">
        {RANGES.map((range, index) => (
          <span
            key={range}
            className={`rounded-sm px-2 py-1 font-mono text-3xs ${
              index === 1 ? "bg-brand/15 text-brand" : "text-text-tertiary"
            }`}
          >
            {range}
          </span>
        ))}
      </div>

      <dl className="grid grid-cols-4 border-t border-border-muted">
        {[
          { label: "Open", value: fmtMoney(Number(latest.open), data.currency) },
          { label: "High", value: fmtMoney(Number(latest.high), data.currency) },
          { label: "Low", value: fmtMoney(Number(latest.low), data.currency) },
          { label: "Vol", value: fmtVolume(latest.volume) },
        ].map((stat) => (
          <div key={stat.label} className="px-4 py-3">
            <dt className="font-mono text-3xs tracking-[0.12em] text-text-tertiary uppercase">
              {stat.label}
            </dt>
            <dd className="mt-1 font-mono text-xs tabular-nums">{stat.value}</dd>
          </div>
        ))}
      </dl>
    </PanelFrame>
  );
}
