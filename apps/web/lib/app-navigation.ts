export type NavigationItem = {
  label: string;
  href: string;
  matches: readonly string[];
};

export type NavigationGroup = NavigationItem & {
  items?: readonly NavigationItem[];
};

export const APP_NAVIGATION: readonly NavigationGroup[] = [
  { label: "Home", href: "/dashboard", matches: ["/dashboard"] },
  { label: "Markets", href: "/markets", matches: ["/markets"] },
  {
    label: "Research",
    href: "/screener",
    matches: ["/screener", "/compare", "/recommendations", "/news", "/stocks"],
    items: [
      { label: "Screener", href: "/screener", matches: ["/screener"] },
      { label: "Compare", href: "/compare", matches: ["/compare"] },
      {
        label: "Recommendations",
        href: "/recommendations",
        matches: ["/recommendations"],
      },
      { label: "News", href: "/news", matches: ["/news"] },
    ],
  },
  {
    label: "Trade",
    href: "/trade",
    matches: ["/trade", "/orders", "/backtest"],
    items: [
      { label: "Trade ticket", href: "/trade", matches: ["/trade"] },
      { label: "Orders", href: "/orders", matches: ["/orders"] },
      { label: "Backtest", href: "/backtest", matches: ["/backtest"] },
    ],
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    matches: ["/portfolio", "/watchlist", "/trades"],
    items: [
      { label: "Overview", href: "/portfolio", matches: ["/portfolio"] },
      { label: "Watchlist", href: "/watchlist", matches: ["/watchlist"] },
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

export function pathMatches(pathname: string, prefixes: readonly string[]): boolean {
  const path = pathname.split(/[?#]/, 1)[0];
  return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function getActiveNavigation(pathname: string): {
  groupHref: string | null;
  itemHref: string | null;
} {
  const group = APP_NAVIGATION.find((entry) => pathMatches(pathname, entry.matches));
  if (!group) return { groupHref: null, itemHref: null };

  const item = group.items?.find((entry) => pathMatches(pathname, entry.matches));
  return {
    groupHref: group.href,
    itemHref: item?.href ?? (group.items ? null : group.href),
  };
}
