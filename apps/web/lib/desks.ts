/**
 * A7.13: the four desk presets (owner, 27 Nov 2026: Swing, Compounder,
 * Derivatives, Quant). Each is a view over existing pages, not a new shell: the
 * tools to open, a screen to start from, and a chart look for the stock page.
 */

export type Desk = {
  id: "swing" | "compounder" | "derivatives" | "quant";
  name: string;
  summary: string;
  tools: { label: string; href: string }[];
  screen: Record<string, string>;
  chart: { indicators: string[]; type?: string; tab?: string };
};

export const DESKS: Desk[] = [
  {
    id: "swing",
    name: "Swing Desk",
    summary: "Trend and momentum over days to weeks: strength, structure and a plan before entry.",
    tools: [
      { label: "Screener", href: "/screener" },
      { label: "Checklist", href: "/checklist" },
      { label: "Charts", href: "/charts" },
      { label: "Alerts", href: "/alerts" },
      { label: "Replay", href: "/replay" },
    ],
    screen: {
      above_sma_50: "1",
      above_sma_200: "1",
      near_52w_high: "1",
      sort: "momentum",
      momentum_days: "63",
    },
    chart: { indicators: ["ema_20", "sma_50", "rsi_14", "rsline"] },
  },
  {
    id: "compounder",
    name: "Compounder Desk",
    summary:
      "Quality businesses held for years: returns on capital, valuation bands and the filings.",
    tools: [
      { label: "Screener", href: "/screener" },
      { label: "Filings", href: "/filings" },
      { label: "Theses", href: "/theses" },
      { label: "Macro", href: "/macro" },
      { label: "Capital gains", href: "/portfolio/tax" },
    ],
    screen: { roe_min: "15", de_max: "1", sort: "mcap", dir: "desc" },
    chart: { indicators: ["sma_200"], type: "line", tab: "financials" },
  },
  {
    id: "derivatives",
    name: "Derivatives Desk",
    summary:
      "Volatility and options: implied against realised, skew, exposure and defined-risk payoffs.",
    tools: [
      { label: "Trade (strategy builder)", href: "/trade" },
      { label: "Macro", href: "/macro" },
      { label: "Event study", href: "/event-study" },
      { label: "Alerts", href: "/alerts" },
    ],
    screen: { hv_max: "60", mcap_min_bn: "50", sort: "mcap", dir: "desc" },
    chart: { indicators: ["bb_20_2", "atr_14", "hv_20"], tab: "options" },
  },
  {
    id: "quant",
    name: "Quant Desk",
    summary:
      "Rules tested before they are trusted: backtests, factors, experiments and optimisation.",
    tools: [
      { label: "Backtest", href: "/backtest" },
      { label: "Experiments", href: "/backtest/experiments" },
      { label: "Event study", href: "/event-study" },
      { label: "Pairs lab", href: "/pairs" },
      { label: "Optimiser", href: "/optimise" },
    ],
    screen: { sort: "momentum", momentum_days: "252" },
    chart: { indicators: ["sma_50", "sma_200", "macd", "obv"] },
  },
];

export function deskById(id: string | undefined): Desk | undefined {
  return DESKS.find((d) => d.id === id);
}

export function deskScreenHref(desk: Desk): string {
  return `/screener?${new URLSearchParams(desk.screen).toString()}`;
}

/** The stock page with the desk's chart look (and tab when it has one). */
export function deskChartHref(desk: Desk, ticker: string): string {
  const q = new URLSearchParams({ indicators: desk.chart.indicators.join(",") });
  if (desk.chart.type) q.set("type", desk.chart.type);
  if (desk.chart.tab) q.set("tab", desk.chart.tab);
  return `/stocks/${encodeURIComponent(ticker.trim().toUpperCase())}?${q.toString()}`;
}
