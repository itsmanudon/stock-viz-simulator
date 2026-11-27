"use client";

/**
 * "Everything in the workspace" as the workspace's own ⌘K palette (owner,
 * 27 Nov 2026), in place of a row of tiles: the same jump-to box people get
 * in the product, working here on the six main surfaces.
 *
 * - Typing filters by name and description; ↑/↓ move the selection (and
 *   wrap), Enter opens it, Escape clears the box. Pointer hover and focus
 *   select a row too. Every row is a real link, so the list works without
 *   the box. The panel keeps its height while filtering, so the page does
 *   not jump.
 * - From `lg`, the selected surface is described in a preview beside the
 *   list; below it each row carries its own description.
 * - With motion allowed, the empty box's placeholder cycles through the
 *   surface names.
 *
 * Each line describes what the surface does today, nothing it does not.
 */

import {
  ArrowRight,
  BriefcaseBusiness,
  ChartCandlestick,
  CornerDownLeft,
  FlaskConical,
  ListChecks,
  ListFilter,
  type LucideIcon,
  ScrollText,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState } from "react";

import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

type Surface = {
  icon: LucideIcon;
  label: string;
  href: string;
  lead: string;
  detail: string;
};

export const SURFACES: Surface[] = [
  {
    icon: ChartCandlestick,
    label: "Markets",
    href: "/markets",
    lead: "Every tracked symbol.",
    detail: "Latest stored close and daily change, sortable.",
  },
  {
    icon: ListFilter,
    label: "Screener",
    href: "/screener",
    lead: "Narrow the universe.",
    detail: "Filter tracked symbols by the metrics you care about.",
  },
  {
    icon: ListChecks,
    label: "Checklist",
    href: "/checklist",
    lead: "Six published conditions.",
    detail: "Each with its formula and evidence grade, per symbol. Not investment advice.",
  },
  {
    icon: FlaskConical,
    label: "Backtest",
    href: "/backtest",
    lead: "Test before you trade.",
    detail: "Run a strategy over stored daily history and read the equity curve.",
  },
  {
    icon: ScrollText,
    label: "Paper trading",
    href: "/trade",
    lead: "$100,000 to practise with.",
    detail: "Market and limit orders, filled at stored daily closes.",
  },
  {
    icon: BriefcaseBusiness,
    label: "Portfolio",
    href: "/portfolio",
    lead: "Keep score.",
    detail: "Positions, value history, dividends and a trading journal.",
  },
];

export function filterSurfaces(query: string, list: Surface[] = SURFACES): Surface[] {
  const q = query.trim().toLowerCase();
  if (!q) return list;
  return list.filter((s) => `${s.label} ${s.lead} ${s.detail}`.toLowerCase().includes(q));
}

export function WorkspacePalette() {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [hint, setHint] = useState(0);
  const [focused, setFocused] = useState(false);

  const results = useMemo(() => filterSurfaces(query), [query]);
  const safe = results.length ? Math.min(active, results.length - 1) : -1;
  const selected = safe >= 0 ? results[safe] : null;

  // The placeholder walks through the names while the box is idle.
  useEffect(() => {
    if (focused || query || mediaMatches("(prefers-reduced-motion: reduce)")) return;
    const timer = setInterval(() => setHint((h) => (h + 1) % SURFACES.length), 2200);
    return () => clearInterval(timer);
  }, [focused, query]);

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!results.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((safe + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((safe - 1 + results.length) % results.length);
    } else if (event.key === "Enter" && selected) {
      event.preventDefault();
      router.push(selected.href);
    } else if (event.key === "Escape") {
      setQuery("");
      setActive(0);
    }
  }

  return (
    <div className="mt-8 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="flex min-h-[35rem] flex-col overflow-hidden rounded-3xl border border-border-muted bg-card/70 shadow-2xl shadow-black/20 backdrop-blur-xl">
        <label className="flex items-center gap-3 border-b border-border-muted px-5 py-4">
          <Search className="size-5 shrink-0 text-text-tertiary" aria-hidden />
          <input
            type="search"
            aria-label="Filter the workspace"
            value={query}
            aria-controls={listId}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={`Jump to ${SURFACES[hint].label}…`}
            className="min-w-0 flex-1 bg-transparent text-lg text-foreground outline-none placeholder:text-text-tertiary [&::-webkit-search-cancel-button]:hidden"
          />
          <kbd className="hidden shrink-0 items-center gap-1 rounded-md border border-border-muted bg-surface-secondary px-2 py-1 font-mono text-sm text-text-secondary sm:inline-flex">
            ⌘K
          </kbd>
        </label>

        <ul id={listId} aria-label="Workspace surfaces" className="grid flex-1 content-start gap-1 p-2">
          {results.map((surface, index) => {
            const on = index === safe;
            return (
              <li key={surface.href}>
                <Link
                  href={surface.href}
                  data-active={on || undefined}
                  onPointerEnter={() => setActive(index)}
                  onFocus={() => setActive(index)}
                  className="group flex items-center gap-4 rounded-2xl px-3 py-3 transition-colors focus-visible:outline-2 focus-visible:outline-ring data-active:bg-surface-secondary"
                >
                  <span
                    className={cn(
                      "grid size-10 shrink-0 place-items-center rounded-xl border border-border-muted transition-colors",
                      on ? "border-brand/40 bg-brand/10" : "bg-surface-secondary",
                    )}
                  >
                    <surface.icon
                      className={cn("size-4", on ? "text-brand" : "text-text-secondary")}
                      aria-hidden
                    />
                  </span>
                  <span className="grid min-w-0 flex-1">
                    <span className="text-base font-medium text-foreground">{surface.label}</span>
                    <span className="text-sm text-text-tertiary lg:hidden">
                      {surface.lead} {surface.detail}
                    </span>
                    <span className="hidden text-sm text-text-tertiary lg:block">
                      {surface.lead}
                    </span>
                  </span>
                  <CornerDownLeft
                    aria-hidden
                    className={cn(
                      "size-4 shrink-0 text-text-tertiary transition-opacity",
                      on ? "opacity-100" : "opacity-0",
                    )}
                  />
                </Link>
              </li>
            );
          })}
          {results.length === 0 ? (
            <li className="px-3 py-6 text-base text-text-secondary">
              Nothing in the workspace matches “{query.trim()}”.
            </li>
          ) : null}
        </ul>

        <p className="border-t border-border-muted px-5 py-3 text-sm text-text-tertiary">
          ↑ ↓ to move, Enter to open. Inside the workspace, ⌘K or Ctrl+K opens this from any page.
        </p>
      </div>

      {/* The preview: what the selected surface is for. Desktop only; phones
          read the same words in each row. */}
      <div
        aria-hidden
        className="relative hidden overflow-hidden rounded-3xl border border-border-muted bg-linear-to-b from-card to-background p-8 lg:flex lg:flex-col"
      >
        {selected ? (
          <div key={selected.href} className="page-enter flex flex-1 flex-col">
            <span className="grid size-14 place-items-center rounded-2xl border border-brand/30 bg-brand/10">
              <selected.icon className="size-6 text-brand" aria-hidden />
            </span>
            <p className="mt-8 text-4xl font-medium tracking-[-0.03em]">{selected.label}</p>
            <p className="mt-3 text-xl text-foreground">{selected.lead}</p>
            <p className="mt-2 max-w-sm text-base leading-7 text-text-secondary">
              {selected.detail}
            </p>
            <Link
              href={selected.href}
              tabIndex={-1}
              className="mt-auto inline-flex items-center gap-2 pt-8 text-base font-medium text-foreground hover:text-brand"
            >
              Open {selected.label}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
        ) : (
          <p className="m-auto text-base text-text-tertiary">Try “trade” or “history”.</p>
        )}
        <span aria-hidden className="brand-glow -right-24 -bottom-24 -z-10 size-72 opacity-50" />
      </div>
    </div>
  );
}
