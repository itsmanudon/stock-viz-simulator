/**
 * How the stock chart draws its prices (A3.1, M2.3): the chart type, the price
 * scale and adjusted or raw prices. All three are URL state on the stock page
 * (`?type=`, `?scale=`, `?adjustment=`), left out of links at their defaults.
 */

export const CHART_TYPES = [
  { value: "candles", label: "Candles" },
  { value: "hollow", label: "Hollow candles" },
  { value: "bars", label: "OHLC bars" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  // Computed in the browser from the stored bars, so never a stored price.
  { value: "heikin-ashi", label: "Heikin-Ashi (derived)" },
] as const;
export type ChartType = (typeof CHART_TYPES)[number]["value"];

export const CHART_SCALES = [
  { value: "linear", label: "Linear", short: "Lin" },
  { value: "log", label: "Logarithmic", short: "Log" },
  { value: "percent", label: "Percent", short: "%" },
] as const;
export type ChartScale = (typeof CHART_SCALES)[number]["value"];

export const PRICE_ADJUSTMENTS = [
  { value: "adjusted", label: "Adjusted" },
  { value: "raw", label: "Raw" },
] as const;
export type PriceAdjustment = (typeof PRICE_ADJUSTMENTS)[number]["value"];

export const RAW_UNAVAILABLE_NOTE = "Only adjusted prices are stored for this symbol";

export type ChartView = { type: ChartType; scale: ChartScale; adjustment: PriceAdjustment };

export const DEFAULT_CHART_VIEW: ChartView = {
  type: "candles",
  scale: "linear",
  adjustment: "adjusted",
};

function pick<T extends string>(
  options: readonly { value: T }[],
  raw: string | undefined,
  fallback: T,
): T {
  return options.some((o) => o.value === raw) ? (raw as T) : fallback;
}

export function parseChartView(query: {
  type?: string;
  scale?: string;
  adjustment?: string;
}): ChartView {
  return {
    type: pick(CHART_TYPES, query.type, DEFAULT_CHART_VIEW.type),
    scale: pick(CHART_SCALES, query.scale, DEFAULT_CHART_VIEW.scale),
    adjustment: pick(PRICE_ADJUSTMENTS, query.adjustment, DEFAULT_CHART_VIEW.adjustment),
  };
}

/** Adds the non-default parts of `view` to `params`, in a fixed order. */
export function setChartViewParams(params: URLSearchParams, view: ChartView): void {
  if (view.type !== DEFAULT_CHART_VIEW.type) params.set("type", view.type);
  if (view.scale !== DEFAULT_CHART_VIEW.scale) params.set("scale", view.scale);
  if (view.adjustment !== DEFAULT_CHART_VIEW.adjustment) params.set("adjustment", view.adjustment);
}

export function chartTypeLabel(type: ChartType): string {
  return CHART_TYPES.find((t) => t.value === type)?.label ?? type;
}
