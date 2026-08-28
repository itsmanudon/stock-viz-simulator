"use client";

import {
  ArrowLeftRight,
  BriefcaseBusiness,
  ChartCandlestick,
  House,
  type LucideIcon,
  SearchCode,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { APP_NAVIGATION, getActiveNavigation, homeHref } from "@/lib/app-navigation";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  Home: House,
  Markets: ChartCandlestick,
  Research: SearchCode,
  Trade: ArrowLeftRight,
  Portfolio: BriefcaseBusiness,
  Community: Users,
};

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
    <nav aria-label="Product" className="flex min-h-0 flex-1 flex-col">
      <div className="mb-5 px-3">
        <span className="inline-flex items-center gap-2 text-[11px] font-medium tracking-wide text-muted-foreground">
          <span className="size-1.5 rounded-full bg-brand" aria-hidden />
          EOD data
        </span>
      </div>

      <div className="space-y-1">
        {APP_NAVIGATION.map((group) => {
          const Icon = ICONS[group.label];
          const groupActive = active.groupHref === group.href;
          const href = group.label === "Home" ? homeHref(signedIn) : group.href;

          return (
            <div key={group.href} className="relative">
              <Link
                href={href}
                data-active={groupActive ? "true" : undefined}
                aria-current={groupActive && !group.items ? "page" : undefined}
                onClick={onNavigate}
                className={cn(
                  "group relative flex h-9 items-center gap-3 rounded-sm px-3 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:z-10",
                  groupActive && "bg-surface-secondary text-foreground",
                )}
              >
                {groupActive ? (
                  <span
                    className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-brand"
                    aria-hidden
                  />
                ) : null}
                {Icon ? <Icon className="size-4 shrink-0" aria-hidden /> : null}
                <span>{group.label}</span>
              </Link>

              {group.items ? (
                <div className="ml-5 border-l border-border-muted py-1 pl-3">
                  {group.items.map((item) => {
                    const itemActive = active.itemHref === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={itemActive ? "page" : undefined}
                        onClick={onNavigate}
                        className={cn(
                          "flex min-h-8 items-center rounded-sm px-2 text-xs text-text-tertiary transition-colors hover:bg-surface-hover hover:text-foreground",
                          itemActive && "font-medium text-brand",
                        )}
                      >
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
