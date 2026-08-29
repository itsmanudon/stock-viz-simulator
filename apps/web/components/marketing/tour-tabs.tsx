"use client";

/**
 * Tab shell for the product tour.
 *
 * The tab row doubles as the step rail — `01 Screen › 02 Research › …` — so the
 * four stages of a session are stated once instead of being repeated as a
 * separate "how it works" list further down the page.
 *
 * Only the switching is client-side. Every panel is server-rendered and stays
 * in the DOM (hidden, not unmounted), so the content is present for crawlers
 * and a tab switch never refetches.
 */

import { useEffect, useId, useRef, useState } from "react";

export type TourTab = {
  id: string;
  label: string;
  panel: React.ReactNode;
};

/** Long enough to read a panel before it moves on. */
const ADVANCE_MS = 6000;

export function TourTabs({ tabs }: { tabs: TourTab[] }) {
  const [active, setActive] = useState(0);
  // Auto-advance is a hint that the panels are switchable. Once the reader has
  // said what they want to look at, it stops for good.
  const [engaged, setEngaged] = useState(false);
  const baseId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (engaged) return;
    // The stylesheet can't gate a timer, so check the preference directly.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const timer = setInterval(() => setActive((i) => (i + 1) % tabs.length), ADVANCE_MS);
    return () => clearInterval(timer);
  }, [engaged, tabs.length]);

  const select = (index: number) => {
    setEngaged(true);
    setActive(index);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (delta === 0) return;
    event.preventDefault();
    const next = (active + delta + tabs.length) % tabs.length;
    select(next);
    // Roving focus: the newly selected tab is the only one in the tab order.
    tabRefs.current[next]?.focus();
  };

  return (
    <div>
      <div
        role="tablist"
        aria-label="Product tour"
        onKeyDown={onKeyDown}
        className="flex flex-wrap items-center gap-x-1 gap-y-2"
      >
        {tabs.map((tab, index) => {
          const selected = index === active;
          return (
            <div key={tab.id} className="flex items-center">
              <button
                type="button"
                role="tab"
                id={`${baseId}-tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`${baseId}-panel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                ref={(node) => {
                  tabRefs.current[index] = node;
                }}
                onClick={() => select(index)}
                className={`flex items-baseline gap-2 rounded-full px-3 py-1.5 transition-colors ${
                  selected
                    ? "bg-brand/10 text-brand"
                    : "text-text-tertiary hover:text-text-secondary"
                }`}
              >
                <span className="font-mono text-3xs tabular-nums">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="text-sm font-medium">{tab.label}</span>
              </button>
              {index < tabs.length - 1 ? (
                <span aria-hidden className="px-1 text-text-tertiary/50">
                  ›
                </span>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="panel-inset panel-glow mt-5">
        {tabs.map((tab, index) => (
          <div
            key={tab.id}
            role="tabpanel"
            id={`${baseId}-panel-${tab.id}`}
            aria-labelledby={`${baseId}-tab-${tab.id}`}
            hidden={index !== active}
          >
            {tab.panel}
          </div>
        ))}
      </div>
    </div>
  );
}
