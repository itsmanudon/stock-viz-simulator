"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ICONS, WORKSPACE_ICONS } from "@/components/navigation-icons";
import {
  type NavigationItem,
  SETTINGS_NAVIGATION,
  STATUS_NAVIGATION,
  WORKSPACES,
  getActiveNavigation,
  homeHref,
} from "@/lib/app-navigation";
import { titleCase } from "@/lib/title-case";
import { cn } from "@/lib/utils";

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
  const Icon = NAV_ICONS[item.href];
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "relative flex h-9 items-center gap-3 rounded-md px-3 text-sm text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:z-10",
        active && "bg-linear-to-r from-brand/12 to-transparent font-medium text-foreground",
      )}
    >
      {active ? (
        <span className="nav-active-bar absolute inset-y-2 left-0 w-0.5 rounded-full" aria-hidden />
      ) : null}
      {Icon ? (
        <Icon
          className={cn("size-4 shrink-0 transition-colors", active && "text-brand")}
          aria-hidden
        />
      ) : null}
      <span className="min-w-0 truncate">{item.label}</span>
      {item.note ? (
        <span className="ml-auto shrink-0 rounded-full border border-border-muted px-1.5 py-px font-mono text-3xs text-text-tertiary">
          {item.note}
        </span>
      ) : null}
    </Link>
  );
}

/**
 * Product sidebar navigation (A3.6): the six workspaces from
 * `lib/app-navigation.ts`, each a labelled group of its routes. A workspace
 * heading is not a link; it lights up (`data-active`) while any of its routes
 * is open, including routes without their own item such as `/stocks/AAPL`
 * (Workbench). Status and Settings sit apart at the bottom; Settings and the
 * Books shortcut only for signed-in users, because proxy.ts would send a guest
 * straight to the sign-in wall.
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
  const utilities = signedIn ? [STATUS_NAVIGATION, SETTINGS_NAVIGATION] : [STATUS_NAVIGATION];

  return (
    <nav aria-label="Product" className="flex min-h-full flex-1 flex-col">
      <div className="space-y-4 pb-6">
        {WORKSPACES.map((workspace) => {
          const headingId = `nav-workspace-${workspace.id}`;
          const workspaceActive = active.workspaceId === workspace.id;
          const WorkspaceIcon = WORKSPACE_ICONS[workspace.id];
          const items = workspace.items.filter((item) => signedIn || !item.signedInOnly);
          return (
            // A fieldset is for form controls; a labelled group is the right
            // role for a set of links under a visible section heading.
            <div
              key={workspace.id}
              // biome-ignore lint/a11y/useSemanticElements: navigation, not a form
              role="group"
              aria-labelledby={headingId}
              data-workspace={workspace.id}
              data-active={workspaceActive ? "true" : undefined}
            >
              <p
                id={headingId}
                data-active={workspaceActive ? "true" : undefined}
                className={cn(
                  "flex items-center gap-2 px-3 pb-1.5 text-3xs font-medium tracking-[0.02em] text-text-tertiary",
                  workspaceActive && "text-foreground",
                )}
              >
                <WorkspaceIcon
                  className={cn("size-3 shrink-0", workspaceActive && "text-brand")}
                  aria-hidden
                />
                {titleCase(workspace.label)}
              </p>
              <div className="space-y-0.5">
                {items.map((item) => (
                  <NavLink
                    key={item.href}
                    item={item}
                    href={item.href === "/dashboard" ? homeHref(signedIn) : item.href}
                    active={active.itemHref === item.href}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-auto space-y-0.5 border-t border-border-muted pt-3">
        {utilities.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            href={item.href}
            active={active.itemHref === item.href}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </nav>
  );
}

/**
 * The "EOD · Simulated" tag beside the wordmark. Warning tone, because the
 * token rules reserve it for stale or simulated data, and both apply here:
 * prices are stored end-of-day closes and every fill is paper.
 */
export function SimulatedDataTag() {
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full border border-warning/40 px-1.5 py-0.5 font-mono text-3xs whitespace-nowrap text-warning"
      title="Prices are stored end-of-day closes. Every order is a paper trade."
    >
      EOD · Simulated
    </span>
  );
}
