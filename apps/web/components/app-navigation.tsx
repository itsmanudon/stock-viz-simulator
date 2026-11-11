"use client";

import {
  ArrowLeftRight,
  Bell,
  CalendarDays,
  ChartCandlestick,
  ChartLine,
  ChartNoAxesColumn,
  Filter,
  FlaskConical,
  History,
  House,
  ListOrdered,
  type LucideIcon,
  Newspaper,
  RotateCcw,
  Settings,
  Star,
  Trophy,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  APP_NAVIGATION,
  type NavigationItem,
  SETTINGS_NAVIGATION,
  getActiveNavigation,
  homeHref,
} from "@/lib/app-navigation";
import { cn } from "@/lib/utils";

/** One icon per destination, keyed by href so a label change can't drop it. */
const ICONS: Record<string, LucideIcon> = {
  "/dashboard": House,
  "/markets": ChartCandlestick,
  "/earnings": CalendarDays,
  "/screener": Filter,
  "/recommendations": ChartNoAxesColumn,
  "/compare": ChartLine,
  "/backtest": FlaskConical,
  "/replay": RotateCcw,
  "/news": Newspaper,
  "/trade": ArrowLeftRight,
  "/orders": ListOrdered,
  "/portfolio": Wallet,
  "/watchlist": Star,
  "/alerts": Bell,
  "/trades": History,
  "/leaderboard": Trophy,
  "/settings": Settings,
};

function NavLink({
  item,
  href,
  active,
  onNavigate,
}: {
  item: NavigationItem;
  href: string;
  active: boolean;
  onNavigate?: () => void;
}) {
  const Icon = ICONS[item.href];
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "relative flex h-9 items-center gap-3 rounded-md px-3 text-sm text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:z-10",
        active && "bg-surface-secondary font-medium text-foreground",
      )}
    >
      {active ? (
        <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand" aria-hidden />
      ) : null}
      {Icon ? <Icon className="size-4 shrink-0" aria-hidden /> : null}
      <span>{item.label}</span>
    </Link>
  );
}

/**
 * Product sidebar navigation (Aurora board v3): Home, Markets and Earnings at
 * the top, then labelled sections. A section heading names the group for
 * assistive tech and lights up while one of its routes is open, including
 * routes without their own item such as `/stocks/AAPL`. Settings is kept apart
 * at the bottom and only rendered for signed-in users, because proxy.ts would
 * send a guest straight to the sign-in wall.
 */
export function AppNavigation({
  signedIn,
  onNavigate,
}: {
  signedIn: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const active = getActiveNavigation(pathname);

  return (
    <nav aria-label="Product" className="flex min-h-full flex-1 flex-col">
      <div className="space-y-0.5 pb-6">
        {APP_NAVIGATION.map((group) => {
          if (!group.items) {
            const href = group.label === "Home" ? homeHref(signedIn) : group.href;
            return (
              <NavLink
                key={group.href}
                item={group}
                href={href}
                active={active.itemHref === group.href}
                onNavigate={onNavigate}
              />
            );
          }

          const headingId = `nav-group-${group.label.toLowerCase()}`;
          const groupActive = active.groupHref === group.href;
          return (
            // A fieldset is for form controls; a labelled group is the right
            // role for a set of links under a visible section heading.
            // biome-ignore lint/a11y/useSemanticElements: navigation, not a form
            <div key={group.href} role="group" aria-labelledby={headingId} className="pt-4">
              <p
                id={headingId}
                data-active={groupActive ? "true" : undefined}
                className={cn(
                  "px-3 pb-1.5 text-3xs font-medium tracking-[0.12em] text-text-tertiary uppercase",
                  groupActive && "text-foreground",
                )}
              >
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <NavLink
                    key={item.href}
                    item={item}
                    href={item.href}
                    active={active.itemHref === item.href}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {signedIn ? (
        <div className="mt-auto border-t border-border-muted pt-3">
          <NavLink
            item={SETTINGS_NAVIGATION}
            href={SETTINGS_NAVIGATION.href}
            active={active.itemHref === SETTINGS_NAVIGATION.href}
            onNavigate={onNavigate}
          />
        </div>
      ) : null}
    </nav>
  );
}

/**
 * The "EOD · SIMULATED" tag beside the wordmark. Warning tone, because the
 * token rules reserve it for stale or simulated data, and both apply here:
 * prices are stored end-of-day closes and every fill is paper.
 */
export function SimulatedDataTag() {
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full border border-warning/40 px-1.5 py-0.5 font-mono text-3xs whitespace-nowrap text-warning"
      title="Prices are stored end-of-day closes. Every order is a paper trade."
    >
      EOD · SIMULATED
    </span>
  );
}
