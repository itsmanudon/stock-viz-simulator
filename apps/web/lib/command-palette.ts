/**
 * The command palette's data (A3.6), pure and client-safe. The component is
 * `components/command-palette.tsx`.
 *
 * Three sources:
 * - **Pages**: every sidebar item in `lib/app-navigation.ts` (one map, so a
 *   new route shows up here with no extra work), plus Status and Settings.
 * - **Actions**: the verbs below. Each points at an existing route; "Switch
 *   book…" opens the top bar's book switcher instead of navigating.
 * - **Symbols**: the global ticker search API (`searchSymbols`), in the
 *   component, because it is async.
 * Recent picks are kept in localStorage as a convenience only.
 */

import {
  type NavigationItem,
  UTILITY_NAVIGATION,
  WORKSPACES,
  type WorkspaceId,
} from "@/lib/app-navigation";
import { type BookRef, withBookHref } from "@/lib/book-url";

export type PaletteCommand = {
  id: string;
  kind: "page" | "action";
  label: string;
  /** Where it belongs, shown beside the label: a workspace name. */
  hint: string;
  workspaceId: WorkspaceId | null;
  /** Destination; book pages get the current `?book=` (`resolveCommandHref`). */
  href: string;
  /** Href whose icon the row shows. */
  iconHref: string;
  keywords: readonly string[];
  signedInOnly?: boolean;
  /** Instead of navigating, run a client effect. */
  effect?: "open-book-switcher";
};

/** The window event the book switcher listens for (A3.6). */
export const OPEN_BOOK_SWITCHER_EVENT = "stockviz:open-book-switcher";

type ActionSpec = Omit<PaletteCommand, "kind" | "hint" | "workspaceId" | "iconHref"> & {
  workspaceId: WorkspaceId | null;
  iconHref?: string;
};

const ACTIONS: readonly ActionSpec[] = [
  {
    id: "action:new-backtest",
    label: "New backtest",
    href: "/backtest",
    workspaceId: "quant-lab",
    keywords: ["run", "strategy", "test", "rule"],
  },
  {
    id: "action:new-replay",
    label: "Start a blind replay",
    href: "/replay",
    workspaceId: "quant-lab",
    keywords: ["replay", "session", "practice"],
  },
  {
    id: "action:new-drill",
    label: "Create drill deck",
    href: "/drills/new",
    iconHref: "/drills",
    workspaceId: "quant-lab",
    keywords: ["drill", "deck", "new"],
  },
  {
    id: "action:search-news",
    label: "Search news headlines",
    href: "/news",
    iconHref: "/news",
    workspaceId: "markets",
    keywords: ["news", "headlines", "sentiment", "coverage"],
  },
  {
    id: "action:new-screen",
    label: "New screen",
    href: "/screener",
    workspaceId: "markets",
    keywords: ["screener", "scan", "filter"],
  },
  {
    id: "action:compare",
    label: "Compare symbols",
    href: "/compare",
    workspaceId: "workbench",
    keywords: ["versus", "vs", "chart"],
  },
  {
    id: "action:place-order",
    label: "Place a paper order",
    href: "/trade",
    workspaceId: "portfolio-tax",
    keywords: ["buy", "sell", "ticket", "trade"],
  },
  {
    id: "action:new-alert",
    label: "Create price alert",
    href: "/alerts",
    workspaceId: "portfolio-tax",
    keywords: ["alert", "notify", "trigger"],
  },
  {
    id: "action:journal",
    label: "Open journal and plans",
    href: "/portfolio?tab=journal",
    iconHref: "/portfolio",
    workspaceId: "portfolio-tax",
    keywords: ["journal", "plans", "trade plan", "calendar", "review"],
  },
  {
    id: "action:switch-book",
    label: "Switch book…",
    href: "/settings#books",
    iconHref: "/settings#books",
    workspaceId: "portfolio-tax",
    keywords: ["book", "account", "family", "huf"],
    signedInOnly: true,
    effect: "open-book-switcher",
  },
  {
    id: "action:manage-books",
    label: "Manage books",
    href: "/settings#books",
    workspaceId: "portfolio-tax",
    keywords: ["books", "create book", "archive"],
    signedInOnly: true,
  },
];

function workspaceLabel(id: WorkspaceId | null): string {
  return WORKSPACES.find((w) => w.id === id)?.label ?? "General";
}

function pageCommand(item: NavigationItem, workspaceId: WorkspaceId | null): PaletteCommand {
  return {
    id: `page:${item.href}`,
    kind: "page",
    label: item.label === "Home" ? "Dashboard" : item.label,
    hint: workspaceId ? workspaceLabel(workspaceId) : "General",
    workspaceId,
    href: item.href,
    iconHref: item.href,
    keywords: [...(item.keywords ?? []), "open", "go"],
    signedInOnly: item.signedInOnly,
  };
}

/** Every page and action, in sidebar order, then actions. */
export function buildCommands({ signedIn }: { signedIn: boolean }): PaletteCommand[] {
  const pages = [
    ...WORKSPACES.flatMap((workspace) =>
      workspace.items
        // Books is a shortcut into Settings; the "Manage books" action covers it.
        .filter((item) => item.matches.length > 0)
        .map((item) => pageCommand(item, workspace.id)),
    ),
    ...UTILITY_NAVIGATION.map((item) => pageCommand(item, null)),
  ];
  const actions: PaletteCommand[] = ACTIONS.map((spec) => ({
    ...spec,
    kind: "action",
    hint: workspaceLabel(spec.workspaceId),
    iconHref: spec.iconHref ?? spec.href,
  }));
  return [...pages, ...actions].filter((command) => signedIn || !command.signedInOnly);
}

function words(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9&]+/)
    .filter(Boolean);
}

/**
 * How well `command` matches `query`, 0 for no match. Every query word must
 * start a word of the label, the workspace or a keyword. A label that starts
 * with the whole query ranks first, then label word matches, then keywords.
 */
export function scoreCommand(command: PaletteCommand, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const tokens = words(q);
  if (tokens.length === 0) return 0;
  const labelWords = words(command.label);
  const otherWords = [...words(command.hint), ...command.keywords.flatMap(words)];
  let score = 0;
  for (const token of tokens) {
    // A whole label word ("new" in "New backtest") beats a prefix ("News").
    if (labelWords.includes(token)) score += 4;
    else if (labelWords.some((w) => w.startsWith(token))) score += 3;
    else if (otherWords.some((w) => w.startsWith(token))) score += 1;
    else return 0;
  }
  if (command.label.toLowerCase().startsWith(q)) score += 10;
  return score;
}

/** Matching commands, best first, stable within a score. */
export function filterCommands(
  commands: readonly PaletteCommand[],
  query: string,
  limit = 8,
): PaletteCommand[] {
  return commands
    .map((command, index) => ({ command, index, score: scoreCommand(command, query) }))
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, limit)
    .map((row) => row.command);
}

/** The href to open, carrying the current book onto book pages. */
export function resolveCommandHref(href: string, book: BookRef | null): string {
  return withBookHref(href, book);
}

// ---------------------------------------------------------------------------
// Recent picks (localStorage, a per-browser convenience; never required).

export const RECENT_KEY = "stockviz:palette-recent";
export const RECENT_LIMIT = 5;

export type RecentEntry =
  | { kind: "symbol"; ticker: string; name: string; exchange?: string | null }
  | { kind: "command"; id: string };

function isRecent(value: unknown): value is RecentEntry {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.kind === "symbol") return typeof v.ticker === "string" && typeof v.name === "string";
  if (v.kind === "command") return typeof v.id === "string";
  return false;
}

function recentKey(entry: RecentEntry): string {
  return entry.kind === "symbol" ? `symbol:${entry.ticker}` : entry.id;
}

export function readRecents(storage: Pick<Storage, "getItem"> | null | undefined): RecentEntry[] {
  try {
    const raw = storage?.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isRecent).slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

/** Puts `entry` first, drops its older copy, keeps `RECENT_LIMIT`; returns the list. */
export function pushRecent(
  storage: Pick<Storage, "getItem" | "setItem"> | null | undefined,
  entry: RecentEntry,
): RecentEntry[] {
  const key = recentKey(entry);
  const next = [entry, ...readRecents(storage).filter((e) => recentKey(e) !== key)].slice(
    0,
    RECENT_LIMIT,
  );
  try {
    storage?.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Private windows and blocked storage only lose the convenience.
  }
  return next;
}

/** `window.localStorage`, or null where reading it throws. */
export function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * "News: AAPL" commands for the palette's symbol results (news redesign,
 * 26 Nov 2026): the first few matches open /news filtered to that symbol.
 */
export function newsCommandsFor(tickers: readonly string[], max = 3): PaletteCommand[] {
  return tickers.slice(0, max).map((ticker) => ({
    id: `news:${ticker}`,
    kind: "action",
    label: `News: ${ticker}`,
    hint: "Markets",
    workspaceId: "markets",
    href: `/news?tickers=${encodeURIComponent(ticker)}`,
    iconHref: "/news",
    keywords: ["news", ticker.toLowerCase()],
  }));
}
