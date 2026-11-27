/**
 * The chart workspace's state (A6.8, M2.10): a grid of up to four charts,
 * each with a symbol, an interval, a template and a link colour.
 *
 * The state lives in the URL, so a workspace can be shared and reloaded:
 *
 *   /charts?grid=4&s=AAPL,AAPL,MSFT,TSLA&i=1d,15m,1wk,1d&t=3,,3,&g=blue,blue,,&layout=7
 *
 * - `grid`: `1`, `2v` (side by side), `2h` (stacked) or `4`.
 * - `s`, `i`, `t`, `g`: per pane, comma-separated in reading order: the
 *   symbol, the interval, the template id (empty: the default look) and the
 *   link colour (empty: unlinked).
 * - `wl`: the watchlist panel's link colour (empty: unlinked).
 * - `layout`: the saved layout this state came from (Save updates it).
 *
 * **Linked groups.** Seven colours, the watchlist colour tags. A pane in a
 * colour follows the last symbol chosen in that colour: choosing a symbol in
 * one blue pane (or in a blue watchlist) moves every blue pane, and nothing
 * else. A pane that joins a colour takes that colour's symbol. Panes of one
 * colour therefore always share a symbol; a URL that says otherwise is read
 * with the first pane's symbol for the colour.
 *
 * No client store: the URL is the state and React context carries the
 * crosshair (`components/chart-layouts/layout-workspace.tsx`).
 */

import type { ChartScale, ChartType } from "@/lib/chart-view";
import { INTRADAY_INTERVALS, STOCK_INTERVALS, type StockInterval } from "@/lib/stock-workspace";
import { LIST_COLOURS } from "@/lib/watchlist-columns";

export const CHART_GRIDS = [
  { value: "1", label: "One chart", panes: 1 },
  { value: "2v", label: "Two, side by side", panes: 2 },
  { value: "2h", label: "Two, stacked", panes: 2 },
  { value: "4", label: "Four", panes: 4 },
] as const;
export type ChartGrid = (typeof CHART_GRIDS)[number]["value"];

export type LinkColour = (typeof LIST_COLOURS)[number]["key"];
export const LINK_COLOURS = LIST_COLOURS;

export const WORKSPACE_INTERVALS: readonly { value: StockInterval; label: string }[] = [
  ...STOCK_INTERVALS.map((i) => ({ value: i.value, label: i.label })),
  ...INTRADAY_INTERVALS.map((i) => ({
    value: i.value,
    label: i.value === "60m" ? "1 hour" : `${i.minutes} minute${i.minutes > 1 ? "s" : ""}`,
  })),
];

export const DEFAULT_SYMBOL = "AAPL";
/** The default look of a pane without a template: the stock page's defaults. */
export const DEFAULT_LOOK: {
  chartType: ChartType;
  scale: ChartScale;
  indicators: string[];
} = { chartType: "candles", scale: "linear", indicators: ["sma_50"] };

export type WorkspacePane = {
  symbol: string;
  interval: StockInterval;
  templateId: number | null;
  link: LinkColour | null;
};

export type WorkspaceState = {
  grid: ChartGrid;
  panes: WorkspacePane[];
  /** The watchlist panel's link colour. */
  watchlistLink: LinkColour | null;
};

export function paneCount(grid: ChartGrid): number {
  return CHART_GRIDS.find((g) => g.value === grid)?.panes ?? 1;
}

export function isGrid(raw: string | undefined): raw is ChartGrid {
  return CHART_GRIDS.some((g) => g.value === raw);
}

export function isLinkColour(raw: string | null | undefined): raw is LinkColour {
  return LINK_COLOURS.some((c) => c.key === raw);
}

export function linkLabel(link: LinkColour | null): string {
  return link ? (LINK_COLOURS.find((c) => c.key === link)?.label ?? link) : "Unlinked";
}

export function intervalLabel(interval: StockInterval): string {
  return WORKSPACE_INTERVALS.find((i) => i.value === interval)?.label ?? interval;
}

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.^&=-]{0,31}$/;

/** A typed symbol, upper-cased, or null if it can't be one. */
export function cleanSymbol(raw: string): string | null {
  const symbol = raw.trim().toUpperCase();
  return SYMBOL_RE.test(symbol) ? symbol : null;
}

function isInterval(raw: string | undefined): raw is StockInterval {
  return WORKSPACE_INTERVALS.some((i) => i.value === raw);
}

/** Panes of one colour share the first such pane's symbol. */
function linkConsistent(panes: WorkspacePane[]): WorkspacePane[] {
  const first = new Map<LinkColour, string>();
  return panes.map((pane) => {
    if (!pane.link) return pane;
    const symbol = first.get(pane.link);
    if (symbol === undefined) {
      first.set(pane.link, pane.symbol);
      return pane;
    }
    return symbol === pane.symbol ? pane : { ...pane, symbol };
  });
}

export function defaultPane(symbol = DEFAULT_SYMBOL): WorkspacePane {
  return { symbol, interval: "1d", templateId: null, link: null };
}

export type WorkspaceQuery = {
  grid?: string;
  s?: string;
  i?: string;
  t?: string;
  g?: string;
  wl?: string;
  layout?: string;
};

/** True when the URL carries panes (otherwise a saved layout or the default applies). */
export function hasWorkspaceState(query: WorkspaceQuery): boolean {
  return Boolean(query.s);
}

export function parseWorkspace(query: WorkspaceQuery): WorkspaceState {
  const grid: ChartGrid = isGrid(query.grid) ? query.grid : "1";
  const symbols = (query.s ?? "").split(",");
  const intervals = (query.i ?? "").split(",");
  const templates = (query.t ?? "").split(",");
  const links = (query.g ?? "").split(",");
  const panes: WorkspacePane[] = [];
  for (let n = 0; n < paneCount(grid); n += 1) {
    const symbol = cleanSymbol(symbols[n] ?? "") ?? panes.at(-1)?.symbol ?? DEFAULT_SYMBOL;
    const interval = isInterval(intervals[n]) ? intervals[n] : "1d";
    const id = Number(templates[n]);
    const link = links[n];
    panes.push({
      symbol,
      interval: interval as StockInterval,
      templateId: Number.isInteger(id) && id > 0 ? id : null,
      link: isLinkColour(link) ? link : null,
    });
  }
  return {
    grid,
    panes: linkConsistent(panes),
    watchlistLink: isLinkColour(query.wl) ? query.wl : null,
  };
}

/** The workspace URL for a state (and the saved layout it belongs to). */
export function workspaceHref(state: WorkspaceState, layoutId?: number | null): string {
  const params = new URLSearchParams();
  params.set("grid", state.grid);
  params.set("s", state.panes.map((p) => p.symbol).join(","));
  params.set("i", state.panes.map((p) => p.interval).join(","));
  if (state.panes.some((p) => p.templateId !== null)) {
    params.set("t", state.panes.map((p) => (p.templateId === null ? "" : p.templateId)).join(","));
  }
  if (state.panes.some((p) => p.link !== null)) {
    params.set("g", state.panes.map((p) => p.link ?? "").join(","));
  }
  if (state.watchlistLink) params.set("wl", state.watchlistLink);
  if (layoutId) params.set("layout", String(layoutId));
  return `/charts?${params.toString()}`;
}

/** Pane `index` chooses `symbol`: every pane in its colour follows. */
export function choosePaneSymbol(
  state: WorkspaceState,
  index: number,
  symbol: string,
): WorkspaceState {
  const link = state.panes[index]?.link ?? null;
  return {
    ...state,
    panes: state.panes.map((pane, n) =>
      n === index || (link !== null && pane.link === link) ? { ...pane, symbol } : pane,
    ),
  };
}

/** Every pane in `link` follows `symbol` (the watchlist chose it). */
export function chooseColourSymbol(
  state: WorkspaceState,
  link: LinkColour,
  symbol: string,
): WorkspaceState {
  return {
    ...state,
    panes: state.panes.map((pane) => (pane.link === link ? { ...pane, symbol } : pane)),
  };
}

/** The symbol a colour follows now, if any pane is in it. */
export function colourSymbol(state: WorkspaceState, link: LinkColour): string | null {
  return state.panes.find((p) => p.link === link)?.symbol ?? null;
}

/** Pane `index` joins `link` (taking the colour's symbol) or leaves its colour. */
export function choosePaneLink(
  state: WorkspaceState,
  index: number,
  link: LinkColour | null,
): WorkspaceState {
  const groupSymbol = link
    ? state.panes.find((p, n) => n !== index && p.link === link)?.symbol
    : undefined;
  return {
    ...state,
    panes: state.panes.map((pane, n) =>
      n === index ? { ...pane, link, symbol: groupSymbol ?? pane.symbol } : pane,
    ),
  };
}

export function choosePaneInterval(
  state: WorkspaceState,
  index: number,
  interval: StockInterval,
): WorkspaceState {
  return {
    ...state,
    panes: state.panes.map((pane, n) => (n === index ? { ...pane, interval } : pane)),
  };
}

export function choosePaneTemplate(
  state: WorkspaceState,
  index: number,
  templateId: number | null,
): WorkspaceState {
  return {
    ...state,
    panes: state.panes.map((pane, n) => (n === index ? { ...pane, templateId } : pane)),
  };
}

/** A new grid keeps the first panes; new cells start on the last pane's symbol, unlinked. */
export function chooseGrid(state: WorkspaceState, grid: ChartGrid): WorkspaceState {
  const want = paneCount(grid);
  const panes = state.panes.slice(0, want);
  while (panes.length < want) panes.push(defaultPane(panes.at(-1)?.symbol ?? DEFAULT_SYMBOL));
  return { ...state, grid, panes };
}

export function chooseWatchlistLink(
  state: WorkspaceState,
  link: LinkColour | null,
): WorkspaceState {
  return { ...state, watchlistLink: link };
}

/** A saved layout (the API's shape) as workspace state. */
export function layoutState(layout: {
  grid: string;
  panes: readonly {
    symbol: string;
    interval: string;
    template_id: number | null;
    link: string | null;
  }[];
}): WorkspaceState {
  return parseWorkspace({
    grid: layout.grid,
    s: layout.panes.map((p) => p.symbol).join(","),
    i: layout.panes.map((p) => p.interval).join(","),
    t: layout.panes.map((p) => p.template_id ?? "").join(","),
    g: layout.panes.map((p) => p.link ?? "").join(","),
  });
}

/** The API body for saving a state. */
export function layoutBody(state: WorkspaceState): {
  grid: ChartGrid;
  panes: {
    symbol: string;
    interval: StockInterval;
    template_id: number | null;
    link: LinkColour | null;
  }[];
} {
  return {
    grid: state.grid,
    panes: state.panes.map((p) => ({
      symbol: p.symbol,
      interval: p.interval,
      template_id: p.templateId,
      link: p.link,
    })),
  };
}
