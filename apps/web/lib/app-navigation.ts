export type NavigationItem = {
  label: string;
  href: string;
  matches: readonly string[];
};

export type NavigationGroup = NavigationItem & {
  items?: readonly NavigationItem[];
};

/**
 * The product sidebar, in the order of the Aurora board (v3, 11 Nov 2026):
 * three top-level pages, then labelled sections. A section heading is not a
 * link; it only lights up while one of its routes is open (`/stocks/*` counts
 * as Research). Settings sits apart at the bottom and only for signed-in users.
 */
export const APP_NAVIGATION: readonly NavigationGroup[] = [
  { label: "Home", href: "/dashboard", matches: ["/dashboard"] },
  { label: "Markets", href: "/markets", matches: ["/markets"] },
  { label: "Earnings", href: "/earnings", matches: ["/earnings"] },
  {
    label: "Research",
    href: "/screener",
    matches: [
      "/screener",
      "/compare",
      "/recommendations",
      "/news",
      "/stocks",
      "/backtest",
      "/replay",
      "/news-reactions",
    ],
    items: [
      { label: "Screener", href: "/screener", matches: ["/screener"] },
      { label: "Signals", href: "/recommendations", matches: ["/recommendations"] },
      { label: "Compare", href: "/compare", matches: ["/compare"] },
      { label: "Backtest", href: "/backtest", matches: ["/backtest"] },
      { label: "Replay", href: "/replay", matches: ["/replay"] },
      { label: "News", href: "/news", matches: ["/news"] },
      { label: "News reactions", href: "/news-reactions", matches: ["/news-reactions"] },
    ],
  },
  {
    label: "Trade",
    href: "/trade",
    matches: ["/trade", "/orders"],
    items: [
      { label: "Trade ticket", href: "/trade", matches: ["/trade"] },
      { label: "Orders", href: "/orders", matches: ["/orders"] },
    ],
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    matches: ["/portfolio", "/watchlist", "/alerts", "/trades"],
    items: [
      { label: "Overview", href: "/portfolio", matches: ["/portfolio"] },
      { label: "Watchlist", href: "/watchlist", matches: ["/watchlist"] },
      { label: "Alerts", href: "/alerts", matches: ["/alerts"] },
      { label: "Trade history", href: "/trades", matches: ["/trades"] },
    ],
  },
  {
    label: "Community",
    href: "/leaderboard",
    matches: ["/leaderboard"],
    items: [{ label: "Leaderboard", href: "/leaderboard", matches: ["/leaderboard"] }],
  },
] as const;

/** Account settings: protected by proxy.ts, so the sidebar shows it only when signed in. */
export const SETTINGS_NAVIGATION: NavigationItem = {
  label: "Settings",
  href: "/settings",
  matches: ["/settings"],
};

export const RESEARCH_SUBNAV = [
  { href: "/compare", label: "Compare" },
  { href: "/backtest", label: "Backtest" },
  { href: "/recommendations", label: "Signals" },
  { href: "/replay", label: "Replay" },
  { href: "/news-reactions", label: "News reactions" },
] as const;

/**
 * Where the logo and the "Home" nav item point.
 *
 * `/dashboard` is portfolio-backed and sits behind proxy.ts, so sending a
 * signed-out visitor there would bounce them straight to the sign-in wall.
 */
export function homeHref(signedIn: boolean): string {
  return signedIn ? "/dashboard" : "/";
}

export function pathMatches(pathname: string, prefixes: readonly string[]): boolean {
  const path = pathname.split(/[?#]/, 1)[0];
  return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function getActiveNavigation(pathname: string): {
  groupHref: string | null;
  itemHref: string | null;
} {
  if (pathMatches(pathname, SETTINGS_NAVIGATION.matches)) {
    return { groupHref: SETTINGS_NAVIGATION.href, itemHref: SETTINGS_NAVIGATION.href };
  }
  const group = APP_NAVIGATION.find((entry) => pathMatches(pathname, entry.matches));
  if (!group) return { groupHref: null, itemHref: null };

  const item = group.items?.find((entry) => pathMatches(pathname, entry.matches));
  return {
    groupHref: group.href,
    itemHref: item?.href ?? (group.items ? null : group.href),
  };
}
