import { barTimeToUtcSeconds } from "@/lib/api-time";
import type { Bar, IndicatorPoint } from "@/lib/api/types";
import type { PaneSpec } from "@/lib/chart-panes";
import { formatCloseDate } from "@/lib/stock-workspace";

/**
 * The crosshair legend (A3.1, M2.1): the hovered bar's date, OHLC, change
 * against the previous close and volume, and every drawn indicator's value
 * on that bar. With no bar hovered it reads the last bar. The legend always
 * reads the stored bar, also under Heikin-Ashi, whose candles are derived.
 */

export const MISSING = "—";

export type LegendModel = {
  bars: Bar[];
  /** Values by bar time in UTC seconds, so a ts written differently still matches. */
  indicators: { key: string; label: string; values: Map<number, number> }[];
};

export type LegendRow = {
  index: number;
  isLast: boolean;
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  change: string;
  changePct: string;
  /** Sign of the change, for colour: 1, -1, 0, or null without a previous bar. */
  direction: 1 | -1 | 0 | null;
  volume: string;
  indicators: { key: string; label: string; value: string }[];
};

const PRICE = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const VALUE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const VOLUME = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

function num(raw: string | number | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function formatPrice(value: number | null): string {
  return value === null ? MISSING : PRICE.format(value);
}

export function formatIndicatorValue(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? MISSING
    : VALUE.format(value);
}

export function formatVolume(value: number | null): string {
  return value === null ? MISSING : VOLUME.format(value);
}

function signed(value: number, text: string): string {
  return value > 0 ? `+${text}` : value < 0 ? `−${text.replace(/^-/, "")}` : text;
}

export function buildLegendModel(bars: Bar[], panes: PaneSpec[]): LegendModel {
  const indicators: LegendModel["indicators"] = [];
  for (const pane of panes) {
    for (const series of pane.series) {
      if (series.kind !== "line" && series.kind !== "histogram") continue;
      indicators.push({
        key: series.key,
        label: series.label,
        values: new Map(
          series.points.map((p: IndicatorPoint) => [barTimeToUtcSeconds(p.ts), p.value]),
        ),
      });
    }
  }
  return { bars, indicators };
}

/**
 * The legend for bar `index`, or the last bar when `index` is null or out of
 * range. `formatDate` labels the bar (A6.2: intraday bars read their time in
 * the venue's zone); by default the daily date.
 */
export function legendAt(
  model: LegendModel,
  index: number | null,
  formatDate: (ts: string) => string = (ts) => formatCloseDate(ts) ?? ts,
): LegendRow | null {
  const { bars } = model;
  if (!bars.length) return null;
  const i = index === null || index < 0 || index >= bars.length ? bars.length - 1 : index;
  const bar = bars[i];
  const time = barTimeToUtcSeconds(bar.ts);
  const close = num(bar.close);
  const previous = i > 0 ? num(bars[i - 1].close) : null;
  let change = MISSING;
  let changePct = MISSING;
  let direction: LegendRow["direction"] = null;
  if (close !== null && previous !== null) {
    const delta = close - previous;
    direction = delta > 0 ? 1 : delta < 0 ? -1 : 0;
    change = signed(delta, PRICE.format(Math.abs(delta)));
    changePct =
      previous === 0
        ? MISSING
        : `${signed(delta, VALUE.format(Math.abs((delta / previous) * 100)))}%`;
  }
  return {
    index: i,
    isLast: i === bars.length - 1,
    date: formatDate(bar.ts),
    open: formatPrice(num(bar.open)),
    high: formatPrice(num(bar.high)),
    low: formatPrice(num(bar.low)),
    close: formatPrice(close),
    change,
    changePct,
    direction,
    volume: formatVolume(num(bar.volume)),
    indicators: model.indicators.map((ind) => ({
      key: ind.key,
      label: ind.label,
      value: formatIndicatorValue(ind.values.get(time)),
    })),
  };
}

/** The legend as one sentence, for the polite live region. */
export function legendText(row: LegendRow): string {
  const ind = row.indicators.map((i) => `${i.label} ${i.value}`).join(", ");
  return (
    `${row.date}: open ${row.open}, high ${row.high}, low ${row.low}, close ${row.close}, ` +
    `change ${row.change} (${row.changePct}), volume ${row.volume}${ind ? `. ${ind}` : ""}.`
  );
}
