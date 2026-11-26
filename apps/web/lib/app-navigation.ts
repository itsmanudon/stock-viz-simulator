/**
 * The product's navigation map (A3.6): every product route belongs to one of
 * six workspaces, and this file is the only place that says which.
 *
 * - The sidebar (`components/app-navigation.tsx`) draws the workspaces and
 *   their items from `WORKSPACES`.
 * - The command palette (`lib/command-palette.ts`) turns the same items into
 *   its "Pages" results.
 * - Workspace subnavs (`workspaceSubnav`) and page eyebrows
 *   (`workspaceLabelFor`) read it too.
 * - `tests/unit/app-navigation.test.ts` walks `app/(product)/**\/page.tsx` and
 *   fails if a page route is not mapped here.
 *
 * To add a route: add its page, then add an item to its workspace (or, for a
 * route without a sidebar item, add its prefix to the workspace's
 * `extraMatches`). Settings and Status sit apart in `UTILITY_NAVIGATION`.
 *
 * URLs never moved in A3.6: the workspaces group existing routes, so every old
 * link still works.
 */

export type WorkspaceId =
  | "today"
  | "markets"
  | "workbench"
  | "quant-lab"
  | "portfolio-tax"
  | "copilot";

export type NavigationItem = {
  label: string;
  href: string;
  /** Path prefixes that make this item the current page. */
  matches: readonly string[];
  /** Hidden from guests (the route is behind proxy.ts and has no guest view). */
  signedInOnly?: boolean;
  /** A short tag after the label, such as the plan phase of a placeholder. */
  note?: string;
  /** Extra words the command palette matches on. */
  keywords?: readonly string[];
};

export type Workspace = {
  id: WorkspaceId;
  label: string;
  /** One line for the palette and assistive tech. */
  description: string;
  items: readonly NavigationItem[];
  /** Prefixes that belong to the workspace without a sidebar item of their own. */
  extraMatches?: readonly string[];
};

export const WORKSPACES: readonly Workspace[] = [
  {
    id: "today",
    label: "Today",
    description: "Your dashboard and what the account was told",
    items: [
      { label: "Home", href: "/dashboard", matches: ["/dashboard"], keywords: ["dashboard"] },
      {
        label: "Notifications",
        href: "/notifications",
        matches: ["/notifications"],
        keywords: ["inbox", "fills", "fired"],
      },
    ],
  },
  {
    id: "markets",
    label: "Markets",
    description: "The market, the calendar, screens and news",
    items: [
      {
        label: "Overview",
        href: "/markets",
        matches: ["/markets"],
        keywords: ["markets", "breadth", "regime", "symbols"],
      },
      {
        label: "Screener",
        href: "/screener",
        matches: ["/screener"],
        keywords: ["screen", "filter", "scan"],
      },
      {
        label: "Earnings",
        href: "/earnings",
        matches: ["/earnings"],
        keywords: ["calendar", "results"],
      },
      { label: "News", href: "/news", matches: ["/news"], keywords: ["headlines", "aegis"] },
    ],
  },
  {
    id: "workbench",
    label: "Workbench",
    description: "One stock at a time: the chart, checks and comparisons",
    items: [
      {
        label: "Charts",
        href: "/charts",
        matches: ["/charts"],
        signedInOnly: true,
        keywords: ["layouts", "grid", "multi-chart", "templates", "linked"],
      },
      { label: "Setups", href: "/setups", matches: ["/setups"], keywords: ["patterns"] },
      {
        label: "Checklist",
        href: "/checklist",
        matches: ["/checklist", "/recommendations"],
        keywords: ["signals", "rules"],
      },
      { label: "Compare", href: "/compare", matches: ["/compare"], keywords: ["versus", "vs"] },
      {
        label: "Event study",
        href: "/event-study",
        matches: ["/event-study"],
        keywords: ["events", "earnings reaction"],
      },
    ],
    // The stock page (chart, drawings, financials) has no item: the palette
    // and the search open it for a symbol.
    extraMatches: ["/stocks"],
  },
  {
    id: "quant-lab",
    label: "Quant Lab",
    description: "Backtests, saved runs, blind replay and drills",
    items: [
      {
        label: "Backtest",
        href: "/backtest",
        matches: ["/backtest"],
        keywords: ["strategy", "rule", "test"],
      },
      {
        label: "Saved runs",
        href: "/backtest/runs",
        matches: ["/backtest/runs"],
        keywords: ["backtest runs", "results", "experiments"],
      },
      {
        // A7.6 (M7.7): named experiments with hypotheses and their runs.
        label: "Experiments",
        href: "/backtest/experiments",
        matches: ["/backtest/experiments"],
        signedInOnly: true,
        keywords: ["hypothesis", "reproducibility", "rerun"],
      },
      { label: "Replay", href: "/replay", matches: ["/replay"], keywords: ["blind", "session"] },
      { label: "Drills", href: "/drills", matches: ["/drills"], keywords: ["deck", "practice"] },
      {
        label: "News reactions",
        href: "/news-reactions",
        matches: ["/news-reactions"],
        keywords: ["news study"],
      },
    ],
  },
  {
    id: "portfolio-tax",
    label: "Portfolio & Tax",
    description: "Books, holdings, orders, trades, the journal and alerts",
    items: [
      {
        label: "Portfolio",
        href: "/portfolio",
        // A5.5: journal entries (`/portfolio/journal/[id]`) belong to the Journal tab.
        matches: ["/portfolio", "/portfolio/journal"],
        keywords: ["holdings", "positions", "journal", "risk", "round trips", "mae", "mfe"],
      },
      {
        label: "Trade",
        href: "/trade",
        matches: ["/trade"],
        keywords: ["ticket", "order", "buy", "sell"],
      },
      { label: "Orders", href: "/orders", matches: ["/orders"], keywords: ["pending", "blotter"] },
      {
        label: "Trade history",
        href: "/trades",
        matches: ["/trades"],
        keywords: ["fills", "trades", "realized"],
      },
      {
        // A5.3: into the selected imported book (the page explains a paper one).
        label: "Import tradebook",
        href: "/portfolio/import",
        matches: ["/portfolio/import"],
        signedInOnly: true,
        keywords: ["zerodha", "csv", "import", "broker", "console"],
      },
      { label: "Watchlist", href: "/watchlist", matches: ["/watchlist"], keywords: ["lists"] },
      { label: "Alerts", href: "/alerts", matches: ["/alerts"], keywords: ["price alert"] },
      {
        // A7.5: theses with kill switches.
        label: "Theses",
        href: "/theses",
        matches: ["/theses"],
        signedInOnly: true,
        keywords: ["thesis", "memo", "kill rule", "invalidation"],
      },
      {
        // Books are managed in Settings; the item is a shortcut, never "current".
        label: "Books",
        href: "/settings#books",
        matches: [],
        signedInOnly: true,
        keywords: ["accounts", "family", "huf"],
      },
    ],
  },
  {
    id: "copilot",
    label: "AI Copilot",
    description: "A placeholder: the copilot is planned for A8",
    items: [
      {
        label: "Copilot",
        href: "/copilot",
        matches: ["/copilot"],
        note: "A8",
        keywords: ["ai", "assistant"],
      },
    ],
  },
] as const;

/** Account settings: protected by proxy.ts, so the sidebar shows it only when signed in. */
export const SETTINGS_NAVIGATION: NavigationItem = {
  label: "Settings",
  href: "/settings",
  matches: ["/settings"],
  signedInOnly: true,
  keywords: ["account", "preferences", "risk limits", "channels"],
};

/** Data and service status: public, pinned beside Settings. */
export const STATUS_NAVIGATION: NavigationItem = {
  label: "Status",
  href: "/status",
  matches: ["/status"],
  keywords: ["data", "health", "freshness", "pipeline"],
};

/** The bottom rail: routes that belong to no workspace. */
export const UTILITY_NAVIGATION: readonly NavigationItem[] = [
  STATUS_NAVIGATION,
  SETTINGS_NAVIGATION,
];

/**
 * Where the logo and the "Home" nav item point.
 *
 * `/dashboard` is portfolio-backed and sits behind proxy.ts, so sending a
 * signed-out visitor there would bounce them straight to the sign-in wall.
 */
export function homeHref(signedIn: boolean): string {
  return signedIn ? "/dashboard" : "/";
}

function pathOnly(pathname: string): string {
  return pathname.split(/[?#]/, 1)[0];
}

export function pathMatches(pathname: string, prefixes: readonly string[]): boolean {
  const path = pathOnly(pathname);
  return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

/** The longest prefix of `prefixes` that `pathname` sits under, or 0. */
function matchLength(pathname: string, prefixes: readonly string[]): number {
  const path = pathOnly(pathname);
  let best = 0;
  for (const prefix of prefixes) {
    if ((path === prefix || path.startsWith(`${prefix}/`)) && prefix.length > best) {
      best = prefix.length;
    }
  }
  return best;
}

export function workspaceMatches(workspace: Workspace): readonly string[] {
  return [...workspace.items.flatMap((item) => item.matches), ...(workspace.extraMatches ?? [])];
}

/** The workspace that owns `pathname`, or null (public pages and the bottom rail). */
export function workspaceForPath(pathname: string): Workspace | null {
  let best: Workspace | null = null;
  let bestLength = 0;
  for (const workspace of WORKSPACES) {
    const length = matchLength(pathname, workspaceMatches(workspace));
    if (length > bestLength) {
      best = workspace;
      bestLength = length;
    }
  }
  return best;
}

/** The workspace's label for a page eyebrow, or `fallback`. */
export function workspaceLabelFor(pathname: string, fallback = "Research"): string {
  return workspaceForPath(pathname)?.label ?? fallback;
}

/** The item a path opens: the one with the longest matching prefix. */
function itemForPath(pathname: string, items: readonly NavigationItem[]): NavigationItem | null {
  let best: NavigationItem | null = null;
  let bestLength = 0;
  for (const item of items) {
    const length = matchLength(pathname, item.matches);
    if (length > bestLength) {
      best = item;
      bestLength = length;
    }
  }
  return best;
}

export function getActiveNavigation(pathname: string): {
  workspaceId: WorkspaceId | null;
  itemHref: string | null;
} {
  const utility = itemForPath(pathname, UTILITY_NAVIGATION);
  if (utility) return { workspaceId: null, itemHref: utility.href };
  const workspace = workspaceForPath(pathname);
  if (!workspace) return { workspaceId: null, itemHref: null };
  return {
    workspaceId: workspace.id,
    itemHref: itemForPath(pathname, workspace.items)?.href ?? null,
  };
}

/**
 * The tabs under a workspace page's header: the workspace's own items,
 * without shortcuts into other areas (Books opens Settings).
 */
export function workspaceSubnav(pathname: string): { href: string; label: string }[] {
  const workspace = workspaceForPath(pathname);
  if (!workspace) return [];
  return workspace.items
    .filter((item) => item.matches.length > 0)
    .map((item) => ({ href: item.href, label: item.label }));
}
