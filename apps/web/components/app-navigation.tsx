"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { NAV_ICONS, WORKSPACE_ICONS } from "@/components/navigation-icons";
import {
  type NavigationItem,
  SETTINGS_NAVIGATION,
  STATUS_NAVIGATION,
  WORKSPACES,
  type WorkspaceId,
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

const NAV_OPEN_KEY = "stockviz:nav-open";

function readOpenGroups(): WorkspaceId[] | null {
  try {
    const raw = window.localStorage.getItem(NAV_OPEN_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const known = new Set<string>(WORKSPACES.map((w) => w.id));
    return parsed.filter((id): id is WorkspaceId => typeof id === "string" && known.has(id));
  } catch {
    return null;
  }
}

function writeOpenGroups(ids: readonly WorkspaceId[]) {
  try {
    window.localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(ids));
  } catch {
    // A convenience only: private windows and blocked storage keep the default.
  }
}

/**
 * Product sidebar navigation (A3.6, collapsible since the 27 Nov 2026 inside
 * redesign): the six workspaces from `lib/app-navigation.ts`, each a labelled
 * group of its routes. Thirty-odd items no longer fit one screen, so each
 * workspace heading is a disclosure button: Today and the workspace of the
 * open page start open, the rest show their item count, and what the reader
 * opens or closes is remembered per browser (`localStorage["stockviz:nav-open"]`,
 * a convenience only). The workspace of the open page can't be closed while
 * it is current, so the current item is always on screen. The group lights up
 * (`data-active`) while any of its routes is open, including routes without
 * their own item such as `/stocks/AAPL` (Workbench). Status and Settings sit
 * apart at the bottom; Settings and the Books shortcut only for signed-in
 * users, because proxy.ts would send a guest straight to the sign-in wall.
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
  // Groups the reader opened by hand; null until storage is read (or empty).
  const [chosen, setChosen] = useState<WorkspaceId[] | null>(null);

  useEffect(() => {
    setChosen(readOpenGroups());
  }, []);

  const base: WorkspaceId[] = chosen ?? ["today"];
  const open = new Set<WorkspaceId>(base);
  if (active.workspaceId) open.add(active.workspaceId);

  function toggle(id: WorkspaceId) {
    const next = new Set<WorkspaceId>(base);
    if (open.has(id) && id !== active.workspaceId) next.delete(id);
    else next.add(id);
    const ids = WORKSPACES.map((w) => w.id).filter((w) => next.has(w));
    setChosen(ids);
    writeOpenGroups(ids);
  }

  return (
    <nav aria-label="Product" className="flex min-h-full flex-1 flex-col">
      <div className="space-y-1 pb-6">
        {WORKSPACES.map((workspace) => {
          const headingId = `nav-workspace-${workspace.id}`;
          const listId = `nav-workspace-${workspace.id}-items`;
          const workspaceActive = active.workspaceId === workspace.id;
          const expanded = open.has(workspace.id);
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
              data-open={expanded ? "true" : undefined}
              className="nav-group"
            >
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={listId}
                // The current workspace stays open, so its button says so.
                aria-disabled={workspaceActive && expanded ? true : undefined}
                onClick={() => toggle(workspace.id)}
                title={workspaceActive ? `${workspace.label}: the open page is here` : undefined}
                className={cn(
                  "group/ws flex h-8 w-full items-center gap-2 rounded-md px-3 text-left text-2xs font-medium tracking-[0.02em] text-text-tertiary transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-disabled:cursor-default",
                  workspaceActive && "text-foreground",
                )}
              >
                <WorkspaceIcon
                  className={cn("size-3.5 shrink-0", workspaceActive && "text-brand")}
                  aria-hidden
                />
                <span id={headingId} className="min-w-0 flex-1 truncate">
                  {titleCase(workspace.label)}
                </span>
                {expanded ? null : (
                  <span
                    aria-hidden
                    className="rounded-full border border-border-muted px-1.5 font-mono text-3xs leading-4 text-text-tertiary"
                  >
                    {items.length}
                  </span>
                )}
                <ChevronRight
                  aria-hidden
                  className={cn(
                    "size-3.5 shrink-0 transition-transform duration-200 motion-reduce:transition-none",
                    expanded && "rotate-90",
                    workspaceActive && "opacity-0",
                  )}
                />
              </button>
              {expanded ? (
                <div id={listId} className="nav-group-items space-y-0.5 pb-2">
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
              ) : (
                <div id={listId} hidden />
              )}
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
